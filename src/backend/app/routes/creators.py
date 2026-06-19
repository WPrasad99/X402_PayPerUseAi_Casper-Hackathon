"""
Creator API Routes — Profile management, API key management, earnings.

Endpoints:
- POST   /api/v1/creators/profile          — Create/update creator profile
- GET    /api/v1/creators/{wallet}          — Get public creator profile
- GET    /api/v1/creators/{wallet}/agents   — List creator's agents
- GET    /api/v1/creators/{wallet}/earnings — Earnings summary
- GET    /api/v1/creators/{wallet}/analytics — Full analytics
- POST   /api/v1/creators/api-keys          — Store encrypted API key
- GET    /api/v1/creators/api-keys/status/{wallet} — Check key status
- DELETE /api/v1/creators/api-keys/{wallet}/{provider} — Delete key
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app import database as db
from app.core.encryption import encrypt_api_key, get_key_hint
from app.config import settings

router = APIRouter(tags=["Creators"])


# ── Request Models ────────────────────────────────────

class ConfirmWithdrawalIn(BaseModel):
    wallet_address: str
    tx_id: str


class CreateProfileIn(BaseModel):
    wallet_address: str
    display_name: str
    bio: Optional[str] = ""
    avatar_url: Optional[str] = ""
    social_twitter: Optional[str] = ""
    social_github: Optional[str] = ""
    social_website: Optional[str] = ""


class SaveApiKeyIn(BaseModel):
    wallet_address: str
    provider: str  # openai, groq, gemini, huggingface
    api_key: str   # Plaintext — will be encrypted before storage


# ── Profile Routes ────────────────────────────────────

@router.post("/profile")
async def create_or_update_profile(data: CreateProfileIn):
    """Create or update a creator profile. DID is auto-generated."""
    if not data.wallet_address:
        raise HTTPException(status_code=400, detail="Wallet address required")
    if not data.display_name or len(data.display_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Display name must be at least 2 characters")

    result = await db.create_creator_profile(
        wallet_address=data.wallet_address,
        display_name=data.display_name.strip(),
        bio=data.bio or "",
        avatar_url=data.avatar_url or "",
        social_twitter=data.social_twitter or "",
        social_github=data.social_github or "",
        social_website=data.social_website or "",
    )
    return {"status": "success", **result}


@router.get("/{wallet}")
async def get_profile(wallet: str):
    """Get public creator profile."""
    profile = await db.get_creator_profile(wallet)
    if not profile:
        raise HTTPException(status_code=404, detail="Creator profile not found")
    return profile


@router.get("/{wallet}/agents")
async def get_creator_agents(wallet: str):
    """List all agents created by this creator."""
    agents = await db.get_creator_agents(wallet)
    return {"agents": agents}


@router.get("/{wallet}/earnings")
async def get_earnings(wallet: str):
    """Get creator earnings summary."""
    profile = await db.get_creator_profile(wallet)
    if not profile:
        return {
            "summary": {
                "total_earned_motes": 0,
                "total_withdrawn_motes": 0,
                "available_motes": 0
            },
            "history": []
        }

    summary = await db.get_creator_earnings_summary(wallet)
    history = await db.get_creator_earnings_history(wallet, limit=20)
    
    return {
        "summary": summary,
        "history": history,
    }


@router.get("/{wallet}/analytics")
async def get_analytics(wallet: str):
    """Get full creator analytics."""
    profile = await db.get_creator_profile(wallet)
    if not profile:
        return {
            "profile": None,
            "analytics": {
                "total_uses": 0,
                "total_tokens": 0,
                "total_earnings": 0,
                "unique_users": 0,
                "active_agents": 0
            },
            "earnings": {
                "total_earned_motes": 0,
                "total_withdrawn_motes": 0,
                "available_motes": 0
            },
            "agents_count": 0,
        }

    analytics = await db.get_creator_analytics(wallet)
    earnings = await db.get_creator_earnings_summary(wallet)
    agents = await db.get_creator_agents(wallet)

    return {
        "profile": profile,
        "analytics": analytics,
        "earnings": earnings,
        "agents_count": len(agents),
    }


@router.get("/{wallet}/earnings/by-agent")
async def get_earnings_by_agent(wallet: str):
    """Get per-agent earnings breakdown for a creator."""
    breakdown = await db.get_earnings_by_agent(wallet)
    return {"breakdown": breakdown}


# ── API Key Routes ────────────────────────────────────

@router.post("/api-keys")
async def save_api_key(data: SaveApiKeyIn):
    """
    Store a creator's API key (encrypted with AES-256-GCM).
    The plaintext key is encrypted before storage and NEVER returned.
    """
    valid_providers = {"openai", "groq", "gemini", "huggingface"}
    if data.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
        )
    if not data.api_key or len(data.api_key.strip()) < 10:
        raise HTTPException(status_code=400, detail="API key too short")

    # Verify creator profile exists
    profile = await db.get_creator_profile(data.wallet_address)
    if not profile:
        raise HTTPException(status_code=404, detail="Create a creator profile first")

    # Encrypt and store
    encrypted = encrypt_api_key(data.api_key.strip())
    hint = get_key_hint(data.api_key.strip())

    await db.save_creator_api_key(
        creator_wallet=data.wallet_address,
        provider=data.provider,
        encrypted_key=encrypted,
        key_hint=hint,
    )

    return {
        "status": "success",
        "provider": data.provider,
        "key_hint": hint,
        "message": "API key encrypted and stored securely"
    }


@router.get("/api-keys/status/{wallet}")
async def get_api_key_status(wallet: str):
    """Check which providers have keys saved (without revealing keys)."""
    keys = await db.get_creator_api_key_status(wallet)
    return {"keys": keys}


@router.delete("/api-keys/{wallet}/{provider}")
async def delete_api_key(wallet: str, provider: str):
    """Delete a stored API key."""
    await db.delete_creator_api_key(wallet, provider)
    return {"status": "deleted", "provider": provider}


@router.post("/withdraw/confirm")
async def confirm_withdrawal(data: ConfirmWithdrawalIn):
    """
    Execute a real on-chain CSPR transfer from the platform wallet to the creator's wallet.
    
    Flow:
    1. Read creator's available_motes from DB
    2. Sign + broadcast a native CSPR Transfer deploy from platform wallet → creator wallet
    3. Wait for on-chain confirmation (~15s on testnet)
    4. Log withdrawal in DB ledger with the real deploy hash
    5. Return tx hash + CSPR.live explorer link
    """
    from app.services.casper_payout_service import send_creator_payout, MIN_PAYOUT_MOTES

    # 1. Get available balance
    summary = await db.get_creator_earnings_summary(data.wallet_address)
    available_motes = int(summary.get("available_motes", 0))

    if available_motes <= 0:
        raise HTTPException(status_code=400, detail="No earnings available to withdraw")

    if available_motes < MIN_PAYOUT_MOTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Minimum withdrawal is {MIN_PAYOUT_MOTES / 1e9:.1f} CSPR. "
                f"You have {available_motes / 1e9:.6f} CSPR. Keep earning!"
            )
        )

    # 2. Send real on-chain CSPR transfer
    result = await send_creator_payout(
        creator_public_key=data.wallet_address,
        amount_motes=available_motes,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "On-chain transfer failed. Check server logs.")
        )

    deploy_hash = result["deploy_hash"]
    explorer_url = result["explorer_url"]
    amount_motes = result["amount_motes"]

    # 3. Record withdrawal in DB with real deploy hash
    await db.log_creator_earning(
        creator_wallet=data.wallet_address,
        agent_id="",
        amount_motes=amount_motes,
        tx_type="withdrawal",
        on_chain_tx_id=deploy_hash,
    )

    return {
        "status": "confirmed",
        "deploy_hash": deploy_hash,
        "explorer_url": explorer_url,
        "amount_motes": amount_motes,
        "amount_cspr": amount_motes / 1_000_000_000,
        "message": f"Successfully sent {amount_motes / 1e9:.6f} CSPR to your wallet",
    }


