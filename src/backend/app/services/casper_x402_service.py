"""
Casper x402 Service
Handles all communication with the CSPR.cloud x402 facilitator.
Replaces the old algorand_service.py entirely.

The x402 flow:
  1. Backend returns 402 with PaymentRequirements
  2. Frontend signs EIP-712 authorization via Casper Wallet
  3. Frontend retries with PAYMENT-SIGNATURE header
  4. This service calls /settle on the facilitator
  5. Facilitator settles CEP-18 transfer on Casper Testnet
"""
import httpx
import secrets
import time
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


# ── Payment Requirements Builder ─────────────────────────────────────────────

def build_payment_requirements(
    resource_url: str,
    amount_units: int,
    resource_description: Optional[str] = None
) -> dict:
    """
    Build the PaymentRequirements object that gets returned in 402 responses.
    
    Args:
        resource_url: The full URL of the AI resource being accessed
        amount_units: Cost in CEP-18 base units (e.g. 1000 = 10 PAIT with 2 decimals)
        resource_description: Human readable description
    
    Returns:
        PaymentRequirements dict conforming to x402 spec
    """
    return {
        "scheme": "exact",
        "network": settings.casper_network,           # "casper:casper-test"
        # payTo must be the PUBLIC KEY hex (e.g. "02024370ec...") so the frontend
        # can use CLPublicKey.fromHex(payTo) to build the native transfer deploy.
        "payTo": settings.platform_public_key or settings.platform_account_hash,
        "amount": str(amount_units),
        "asset": "casper",
        "maxTimeoutSeconds": settings.max_timeout_seconds,
        "resource": {
            "url": resource_url,
            "description": resource_description or "PayPerUseAI API Access",
            "mimeType": "application/json"
        }
    }


def build_402_response(resource_url: str, amount_units: int, description: str = "") -> dict:
    """
    Build the complete 402 Payment Required response body.
    """
    return {
        "x402Version": 2,
        "error": "Payment Required",
        "accepts": [
            build_payment_requirements(resource_url, amount_units, description)
        ]
    }


# ── Facilitator API Client ────────────────────────────────────────────────────

def _get_headers() -> dict:
    """Returns auth headers for CSPR.cloud facilitator."""
    return {
        "authorization": settings.cspr_x402_api_key,
        "accept": "application/json",
        "content-type": "application/json"
    }


async def verify_payment(payment_payload: dict, payment_requirements: dict) -> dict:
    """
    Verify a payment payload without settling on-chain.
    Use this for a quick pre-check before settling.
    
    Returns:
        {isValid: bool, payer: str} or {isValid: false, invalidReason: str, invalidMessage: str}
    """
    url = f"{settings.cspr_x402_facilitator_url}/verify"
    body = {
        "paymentPayload": payment_payload,
        "paymentRequirements": payment_requirements
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=body, headers=_get_headers())
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"x402 verify HTTP error: {e.response.status_code} - {e.response.text}")
            return {"isValid": False, "invalidReason": "facilitator_error", "invalidMessage": str(e)}
        except Exception as e:
            logger.error(f"x402 verify error: {e}")
            return {"isValid": False, "invalidReason": "network_error", "invalidMessage": str(e)}


async def settle_payment(payment_payload: dict, payment_requirements: dict) -> dict:
    """
    Verify + settle a payment on the Casper Network.
    
    Returns:
        {success: bool, transaction: str, network: str, payer: str}
        or {success: false, errorReason: str, errorMessage: str}
    """
    url = f"{settings.cspr_x402_facilitator_url}/settle"
    body = {
        "paymentPayload": payment_payload,
        "paymentRequirements": payment_requirements
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, json=body, headers=_get_headers())
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"x402 settle result: success={result.get('success')}, tx={result.get('transaction', '')[:16]}...")
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"x402 settle HTTP error: {e.response.status_code} - {e.response.text}")
            return {
                "success": False,
                "errorReason": "facilitator_http_error",
                "errorMessage": f"HTTP {e.response.status_code}: {e.response.text}",
                "transaction": "",
                "network": settings.casper_network,
                "payer": ""
            }
        except Exception as e:
            logger.error(f"x402 settle error: {e}")
            return {
                "success": False,
                "errorReason": "network_error",
                "errorMessage": str(e),
                "transaction": "",
                "network": settings.casper_network,
                "payer": ""
            }


# ── Payment Payload Parser ────────────────────────────────────────────────────

def parse_payment_signature_header(header_value: str) -> Optional[dict]:
    """
    Parse the PAYMENT-SIGNATURE header sent by the frontend.
    The frontend sends a base64-encoded JSON PaymentPayload.
    
    Returns parsed dict or None if invalid.
    """
    import base64, json
    try:
        decoded = base64.b64decode(header_value).decode("utf-8")
        payload = json.loads(decoded)
        # Validate minimum required fields
        if not payload.get("x402Version"):
            return None
        if not payload.get("payload", {}).get("signature"):
            return None
        return payload
    except Exception as e:
        logger.warning(f"Failed to parse PAYMENT-SIGNATURE header: {e}")
        return None


# ── Cost Calculator ───────────────────────────────────────────────────────────

def calculate_cost_units(input_tokens: int = 0, output_tokens: int = 0) -> int:
    """
    Calculate payment amount in native CSPR motes based on token usage.
    
    1 CSPR = 1,000,000,000 motes
    """
    # Just a simple calculation, e.g. 1,000,000 motes (0.001 CSPR) per output token
    output_cost = output_tokens * 1000000
    input_cost = input_tokens * 200000
    total = output_cost + input_cost
    # Minimum payment 0.1 CSPR
    return max(total, 100000000)


def units_to_display(units: int) -> str:
    """Convert base motes to human-readable CSPR amount."""
    decimals = 9
    divisor = 10 ** decimals
    amount = units / divisor
    return f"{amount:.{decimals}f} CSPR"


# ── Nonce Generator ───────────────────────────────────────────────────────────

def generate_nonce() -> str:
    """Generate a 32-byte random nonce as a 64-char hex string for EIP-712."""
    return secrets.token_hex(32)


def generate_validity_window(timeout_seconds: int = 300) -> tuple[str, str]:
    """
    Generate validAfter and validBefore timestamps for the authorization.
    
    Returns: (validAfter as unix timestamp string, validBefore as unix timestamp string)
    """
    now = int(time.time())
    valid_after = now - 5          # 5 seconds in the past (clock skew tolerance)
    valid_before = now + timeout_seconds
    return str(valid_after), str(valid_before)
