"""
Session route — Casper Edition.
The old Algorand session system (box storage, escrow) is completely removed.
x402 is stateless — no sessions needed. Each request pays independently.

This route is kept as a stub for backwards compatibility and
returns x402-based payment info instead.
"""
from fastapi import APIRouter
from app.config import settings
from app.services.casper_x402_service import units_to_display

router = APIRouter(tags=["Session"])


@router.get("/session/info")
async def get_x402_session_info():
    """
    Returns current x402 payment configuration.
    In x402 mode, there are no persistent sessions — each request pays independently.
    """
    return {
        "mode": "x402_stateless",
        "description": "No sessions in x402 mode. Each AI request requires a fresh signed payment.",
        "network": settings.casper_network,
        "token": settings.cep18_token_symbol,
        "pricing": {
            "chat": units_to_display(100),
            "image": units_to_display(500),
            "query": units_to_display(50),
        }
    }
