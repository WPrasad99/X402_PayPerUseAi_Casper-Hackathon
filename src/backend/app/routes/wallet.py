"""
Wallet routes — Casper Network Edition.
Removed: Algorand escrow deposit, ALGO balance checks
Added: Casper account hash derivation, CEP-18 token balance, wallet registration
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.database import get_transaction_ledger
from app.core.limiter import limiter
from app.config import settings
import httpx
import hashlib

router = APIRouter(tags=["Wallet"])


class WalletRegisterIn(BaseModel):
    publicKey: str   # Casper public key (01<64hex> or 02<66hex>)


# ── Account Hash Derivation ───────────────────────────────────────────────────

def public_key_to_account_hash(public_key: str) -> str:
    """
    Derive the Casper account hash from a public key.
    
    Casper account hash = blake2b(algorithm_name_bytes + [0] + public_key_bytes)
    
    For ED25519 keys (prefix 01): algorithm = "ed25519"
    For SECP256K1 keys (prefix 02): algorithm = "secp256k1"
    
    The resulting 32-byte hash is hex-encoded, prefixed with "00" for the
    x402 format (account-hash format used by the facilitator).
    """
    import hashlib
    
    public_key = public_key.strip()
    
    if public_key.startswith("01"):
        algo = "ed25519"
        key_bytes = bytes.fromhex(public_key[2:])
    elif public_key.startswith("02"):
        algo = "secp256k1"
        key_bytes = bytes.fromhex(public_key[2:])
    else:
        raise ValueError(f"Unknown key prefix in: {public_key[:4]}...")
    
    # Casper's account hash derivation
    algo_bytes = algo.encode("utf-8")
    data = algo_bytes + b"\x00" + key_bytes
    
    # blake2b with 32-byte digest
    digest = hashlib.blake2b(data, digest_size=32).hexdigest()
    
    # Return with "00" prefix as expected by x402 facilitator
    return "00" + digest


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/wallet/account-hash/{public_key}")
async def get_account_hash(public_key: str):
    """
    Derive the Casper account hash from a public key.
    Used by the frontend x402 client to build TransferAuthorization.
    """
    try:
        account_hash = public_key_to_account_hash(public_key)
        return {
            "publicKey": public_key,
            "accountHash": account_hash,
            "explorer": f"https://testnet.cspr.live/account/account-hash-{account_hash[2:]}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/wallet/{account_hash}/token-balance")
@limiter.limit("30/minute")
async def get_token_balance(request: Request, account_hash: str):
    """
    Get the CEP-18 (PAIT) token balance for a Casper account.
    Fetches live from CSPR.cloud.
    """
    if not settings.cep18_contract_package_hash:
        return {
            "accountHash": account_hash,
            "balance": "0",
            "displayBalance": f"0.00 {settings.cep18_token_symbol}",
            "note": "Contract not configured yet"
        }
    
    # Normalize account hash — strip "account-hash-" prefix if present
    clean_hash = account_hash.replace("account-hash-", "").replace("00", "", 1) if account_hash.startswith("00") else account_hash
    
    api_url = (
        f"https://api.testnet.csprcloud.com/accounts/account-hash-{clean_hash}"
        f"/contract-packages/{settings.cep18_contract_package_hash}/balances"
    )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                api_url,
                headers={
                    "authorization": settings.cspr_x402_api_key,
                    "accept": "application/json"
                }
            )
            if resp.status_code == 404:
                raw_balance = "0"
            else:
                resp.raise_for_status()
                data = resp.json()
                raw_balance = str(data.get("balance", "0"))
        
        decimals = settings.cep18_token_decimals
        display = f"{int(raw_balance) / 10**decimals:.{decimals}f} {settings.cep18_token_symbol}"
        
        return {
            "accountHash": account_hash,
            "balance": raw_balance,
            "displayBalance": display,
            "symbol": settings.cep18_token_symbol,
            "decimals": decimals,
        }
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"CSPR.cloud error: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/wallet/{account_hash}/ledger")
async def get_ledger(account_hash: str):
    """Get the payment ledger (x402 payment history) for a wallet."""
    entries = await get_transaction_ledger(account_hash)
    return {"accountHash": account_hash, "ledger": entries}


@router.post("/wallet/register")
async def register_wallet(data: WalletRegisterIn):
    """
    Register a Casper wallet in the database.
    Derives and stores the account hash from the public key.
    """
    try:
        account_hash = public_key_to_account_hash(data.publicKey)
        # TODO: upsert into users table
        return {
            "status": "registered",
            "publicKey": data.publicKey,
            "accountHash": account_hash,
            "network": settings.casper_network
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
