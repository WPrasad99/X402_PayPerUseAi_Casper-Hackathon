"""
Session-Based Payment Store
============================
Implements an in-memory session store for the X-402 "pay once per session" flow.

Flow:
  1. User sends first chat request → X-402 middleware returns 402
  2. Frontend shows wallet popup with session budget (default 1 CSPR)
  3. User approves → frontend calls POST /api/v1/payment/session/create with payment proof
  4. Backend settles on-chain → creates session token → returns to frontend
  5. Frontend stores session token → sends X-Session-Token header on all subsequent requests
  6. X-402 middleware checks session token, deducts per-message cost, no new wallet popup
  7. When session balance runs low → frontend shows "refill" prompt

Sessions expire after SESSION_TTL_SECONDS (default 2 hours).
"""

import time
import secrets
import logging
from typing import Optional
from datetime import datetime, timezone

from app.database import (
    db_create_payment_session,
    db_get_payment_session,
    db_deduct_payment_session,
    db_invalidate_payment_session
)

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
SESSION_TTL_SECONDS = 7200          # 2 hours
MIN_BALANCE_TO_REFILL_UNITS = 50_000_000   # 0.05 CSPR — warn user to refill
DEFAULT_SESSION_BUDGET_UNITS = 1_000_000_000  # 1 CSPR default session budget


def _is_expired(created_at: datetime) -> bool:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds() > SESSION_TTL_SECONDS


def _format_session(row: dict) -> dict:
    created_at = row['created_at']
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
        
    return {
        "token": row["token"],
        "payer": row["payer_wallet"],
        "initial_cspr": row["initial_units"] / 1e9,
        "remaining_cspr": row["remaining_units"] / 1e9,
        "remaining_units": row["remaining_units"],
        "tx_hash": row["tx_hash"],
        "messages_count": row["messages_count"],
        "created_at": created_at.timestamp(),
        "expires_at": created_at.timestamp() + SESSION_TTL_SECONDS,
        "low_balance": row["remaining_units"] < MIN_BALANCE_TO_REFILL_UNITS,
    }


async def create_session(
    payer_wallet: str,
    amount_units: int,
    tx_hash: str
) -> dict:
    """
    Create a new payment session securely in the PostgreSQL database.
    """
    token = secrets.token_urlsafe(32)
    
    await db_create_payment_session(
        token=token,
        payer_wallet=payer_wallet,
        initial_units=amount_units,
        tx_hash=tx_hash
    )
    
    logger.info(
        f"SessionPay: Created persistent session for {payer_wallet[:16]}... | "
        f"{amount_units / 1e9:.4f} CSPR | token={token[:12]}..."
    )
    
    row = await db_get_payment_session(token)
    return _format_session(row)


async def get_session(token: str) -> Optional[dict]:
    """Look up a session by token in DB. Returns None if not found or expired."""
    row = await db_get_payment_session(token)
    if not row:
        return None
        
    if _is_expired(row["created_at"]):
        await db_invalidate_payment_session(token)
        logger.info(f"SessionPay: Expired persistent session removed: {token[:12]}...")
        return None
        
    return row


async def deduct_from_session(token: str, cost_units: int) -> Optional[dict]:
    """
    Deduct cost_units from the session's balance via DB.
    This uses an atomic RETURNING query, making it safe for concurrent high-scale requests.
    """
    # 1. First check if it exists and hasn't expired
    row = await get_session(token)
    if not row:
        return None
        
    if row["remaining_units"] < cost_units:
        logger.warning(
            f"SessionPay: Insufficient balance for {token[:12]}... "
            f"(needs {cost_units}, has {row['remaining_units']})"
        )
        return None
    
    # 2. Perform atomic deduction
    updated_row = await db_deduct_payment_session(token, cost_units)
    if not updated_row:
        # Another request might have depleted it concurrently
        return None
        
    logger.info(
        f"SessionPay: Deducted {cost_units} units from {token[:12]}... | "
        f"Remaining: {updated_row['remaining_units'] / 1e9:.6f} CSPR"
    )
    return _format_session(updated_row)


async def get_session_info(token: str) -> Optional[dict]:
    """Get session info without modifying it."""
    row = await get_session(token)
    return _format_session(row) if row else None


async def invalidate_session(token: str):
    """Manually invalidate/delete a session."""
    await db_invalidate_payment_session(token)
    logger.info(f"SessionPay: Persistent session invalidated: {token[:12]}...")

