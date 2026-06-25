"""
Payment routes — x402 Edition.
Provides payment requirements info and payment history.
The actual payment enforcement happens in X402PaymentMiddleware.

Removed: Algorand session initiation, escrow deposit flow
Added: Payment requirements endpoint, Casper balance check, payment history
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from app.services.casper_onchain import broadcast_and_confirm
from app.services.casper_x402_service import (
    build_payment_requirements,
    calculate_cost_units,
    units_to_display,
    settle_payment,
    parse_payment_signature_header,
)
from app.services.session_payment import (
    create_session,
    get_session_info,
    deduct_from_session,
    invalidate_session,
    DEFAULT_SESSION_BUDGET_UNITS,
)
from app.core.security import get_current_user
from app.config import settings
import httpx

router = APIRouter(tags=["Payment"])


import asyncio
import logging

logger = logging.getLogger(__name__)

class SessionCreateRequest(BaseModel):
    payment_signature: str      # Base64-encoded PaymentPayload from frontend
    budget_units: int = DEFAULT_SESSION_BUDGET_UNITS  # How much CSPR to deposit


class OnchainSessionCreateRequest(BaseModel):
    deploy: dict                # Signed Casper Deploy JSON from casper-js-sdk
    budget_units: int = DEFAULT_SESSION_BUDGET_UNITS  # Expected session budget in motes



@router.get("/payment/requirements")
async def get_payment_requirements(
    request: Request,
    service_type: str = "chat",
    estimated_tokens: int = 500
):
    """
    Returns the x402 PaymentRequirements for a given AI service.
    Frontend uses this to pre-compute the expected cost before calling the AI endpoint.
    
    Args:
        service_type: "chat" | "image" | "query"
        estimated_tokens: Estimated output tokens for cost preview
    """
    service_costs = {
        "chat": 100,
        "image": 500,
        "query": 50,
    }
    
    base_cost = service_costs.get(service_type, 100)
    # Add token-based estimate on top of base cost
    token_estimate = calculate_cost_units(output_tokens=estimated_tokens)
    total_estimate = max(base_cost, token_estimate)
    
    resource_url = f"{settings.platform_base_url}/api/v1/{service_type}"
    
    return {
        "network": settings.casper_network,
        "token": {
            "name": settings.cep18_token_name,
            "symbol": settings.cep18_token_symbol,
            "decimals": settings.cep18_token_decimals,
            "contractHash": settings.cep18_contract_package_hash,
        },
        "estimatedCost": {
            "units": total_estimate,
            "display": units_to_display(total_estimate),
        },
        "paymentRequirements": build_payment_requirements(
            resource_url=resource_url,
            amount_units=total_estimate,
            resource_description=f"PayPerUseAI {service_type.title()} Access"
        ),
        "facilitator": settings.cspr_x402_facilitator_url,
        "instructions": {
            "step1": "Build a TransferAuthorization with the nonce/validity fields",
            "step2": "Sign it as EIP-712 typed data using Casper Wallet",
            "step3": "Encode the full PaymentPayload as base64 JSON",
            "step4": f"Retry your request with header: PAYMENT-SIGNATURE: <base64>",
        }
    }


@router.get("/payment/config")
async def get_payment_config():
    """
    Returns the Casper x402 configuration for the frontend to initialize.
    Called once on app startup to get network + token info.
    """
    return {
        "network": settings.casper_network,
        "facilitatorUrl": settings.cspr_x402_facilitator_url,
        "token": {
            "name": settings.cep18_token_name,
            "symbol": settings.cep18_token_symbol,
            "decimals": settings.cep18_token_decimals,
            "contractPackageHash": settings.cep18_contract_package_hash,
        },
        "platformAccountHash": settings.platform_account_hash,
        "maxTimeoutSeconds": settings.max_timeout_seconds,
        "pricing": {
            "chat": {"baseUnits": 100, "display": units_to_display(100)},
            "image": {"baseUnits": 500, "display": units_to_display(500)},
            "query": {"baseUnits": 50, "display": units_to_display(50)},
            "perOutputToken": {"units": settings.cost_per_ai_token_units},
        }
    }


@router.get("/payment/balance/{account_hash}")
async def get_token_balance(account_hash: str):
    """
    Fetch the CEP-18 token balance for a Casper account.
    Uses CSPR.cloud REST API to query on-chain state.
    """
    if not account_hash or len(account_hash) < 64:
        raise HTTPException(status_code=400, detail="Invalid account hash format")
    
    if not settings.cep18_contract_package_hash:
        raise HTTPException(status_code=503, detail="CEP-18 contract not configured")
    
    # Query CSPR.cloud for the CEP-18 balance
    api_url = (
        f"https://api.testnet.csprcloud.com/accounts/{account_hash}"
        f"/contract-packages/{settings.cep18_contract_package_hash}/balances"
    )
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                api_url,
                headers={
                    "authorization": settings.cspr_x402_api_key,
                    "accept": "application/json"
                }
            )
            if resp.status_code == 404:
                # Account has no tokens yet
                return {
                    "accountHash": account_hash,
                    "balance": "0",
                    "displayBalance": f"0 {settings.cep18_token_symbol}",
                    "token": settings.cep18_token_symbol
                }
            resp.raise_for_status()
            data = resp.json()
            raw_balance = data.get("balance", "0")
            
            return {
                "accountHash": account_hash,
                "balance": raw_balance,
                "displayBalance": units_to_display(int(raw_balance)),
                "token": settings.cep18_token_symbol,
                "contractHash": settings.cep18_contract_package_hash
            }
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch balance from CSPR.cloud: {e.response.status_code}"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Balance query failed: {str(e)}")


# ── Session Payment Endpoints ─────────────────────────────────────────────────

@router.post("/payment/session/create")
async def create_payment_session(
    body: SessionCreateRequest,
    wallet_address: str = Depends(get_current_user)
):
    """
    Create a payment session after settling a budget on-chain.
    
    The frontend:
      1. Gets a 402 response with payment requirements
      2. Signs a TransferAuthorization for the session budget
      3. POSTs the payment_signature here
      4. Gets back a session_token to use for all subsequent chat requests
    
    Returns:
        { session_token, remaining_cspr, expires_in_seconds, tx_hash }
    """
    # Parse the payment payload
    payment_payload = parse_payment_signature_header(body.payment_signature)
    if not payment_payload:
        raise HTTPException(status_code=400, detail="Invalid payment signature format")

    # Build requirements to validate against
    resource_url = f"{settings.platform_base_url}/api/v1/chat"
    payment_requirements = build_payment_requirements(
        resource_url=resource_url,
        amount_units=body.budget_units,
        resource_description="PayPerUseAI Session Budget"
    )

    # Settle the payment on-chain via CSPR.cloud facilitator
    settle_result = await settle_payment(payment_payload, payment_requirements)

    if not settle_result.get("success"):
        reason = settle_result.get("errorReason", "unknown")
        message = settle_result.get("errorMessage", "Payment settlement failed")
        raise HTTPException(
            status_code=402,
            detail=f"Payment settlement failed: {reason} - {message}"
        )

    # Create session token
    tx_hash = settle_result.get("transaction", "sim_" + wallet_address[:16])
    session = await create_session(
        payer_wallet=wallet_address,
        amount_units=body.budget_units,
        tx_hash=tx_hash,
    )

    return {
        "session_token": session["token"],
        "remaining_cspr": session["remaining_units"] / 1e9,
        "remaining_units": session["remaining_units"],
        "tx_hash": tx_hash,
        "expires_in_seconds": 7200,
        "budget_cspr": body.budget_units / 1e9,
        "message": f"Session created with {body.budget_units / 1e9:.4f} CSPR budget"
    }


@router.get("/payment/session/{session_token}")
async def get_session_status(
    session_token: str,
    wallet_address: str = Depends(get_current_user)
):
    """
    Get current session balance and status.
    Frontend uses this to display the remaining CSPR balance in the UI.
    """
    info = await get_session_info(session_token)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # Security: only the session owner can check it
    if info["payer"] != wallet_address:
        raise HTTPException(status_code=403, detail="Session does not belong to this wallet")

    return info


@router.delete("/payment/session/{session_token}")
async def close_session(
    session_token: str,
    wallet_address: str = Depends(get_current_user)
):
    """Close/invalidate a payment session (e.g. on logout)."""
    info = await get_session_info(session_token)
    if not info:
        return {"message": "Session already closed or not found"}

    if info["payer"] != wallet_address:
        raise HTTPException(status_code=403, detail="Session does not belong to this wallet")

    await invalidate_session(session_token)
    return {"message": "Session closed", "unused_cspr": info.get("remaining_cspr", 0)}


@router.post("/payment/session/create-onchain")
async def create_session_onchain(
    body: OnchainSessionCreateRequest,
    wallet_address: str = Depends(get_current_user)
):
    """
    Create a payment session by broadcasting a signed native CSPR Transfer Deploy.

    Flow:
      1. Receive signed Deploy JSON from the frontend (casper-js-sdk)
      2. Broadcast it to the Casper RPC node (account_put_deploy)
      3. Poll for execution confirmation (up to 90s)
      4. Create in-memory session token and return it
    """
    rpc_url = settings.casper_node_rpc_url

    result = await broadcast_and_confirm(
        rpc_url=rpc_url,
        deploy_json=body.deploy,
        max_wait_seconds=90,
        poll_interval_seconds=3,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=402,
            detail=result.get("error_message", "On-chain transaction failed")
        )

    deploy_hash = result["deploy_hash"]

    # Create in-memory session for this wallet
    session = await create_session(
        payer_wallet=wallet_address,
        amount_units=body.budget_units,
        tx_hash=deploy_hash,
    )

    return {
        "session_token": session["token"],
        "remaining_cspr": session["remaining_units"] / 1e9,
        "remaining_units": session["remaining_units"],
        "tx_hash": deploy_hash,
        "expires_in_seconds": 7200,
        "budget_cspr": body.budget_units / 1e9,
        "message": f"Session funded with {body.budget_units / 1e9:.4f} CSPR on-chain"
    }

