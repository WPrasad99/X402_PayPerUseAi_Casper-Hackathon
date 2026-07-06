"""
x402 FastAPI Middleware
Intercepts requests to protected AI routes and enforces x402 payment.

Flow (Session Mode - preferred):
  1. Request arrives with X-Session-Token header
  2. Middleware checks token in session store
  3. If valid + enough balance → deducts estimated cost → passes through
  4. If expired/insufficient → returns 402 asking for new session

Flow (Per-Request Mode - fallback):
  1. Request arrives at protected route with no session token
  2. Middleware checks for PAYMENT-SIGNATURE header
  3. If missing → returns 402 with PaymentRequirements JSON
  4. If present → settles payment via CSPR.cloud facilitator
  5. If settlement succeeds → passes request to route handler

Protected routes are defined in PROTECTED_ROUTES below.
"""
import json
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.services.casper_x402_service import (
    build_402_response,
    build_payment_requirements,
    parse_payment_signature_header,
    settle_payment,
    calculate_cost_units
)
from app.services.session_payment import (
    get_session,
    deduct_from_session,
    MIN_BALANCE_TO_REFILL_UNITS,
)
from app.config import settings

logger = logging.getLogger(__name__)


# ── Protected Routes Configuration ───────────────────────────────────────────
# Maps route prefixes to (base_cost_units, description)
PROTECTED_ROUTES = {
    "/api/v1/chat": (100_000_000, "AI Chat Access"),         # 0.1 CSPR minimum
    "/api/v1/image": (500_000_000, "AI Image Generation"),   # 0.5 CSPR
    "/api/v1/query": (50_000_000, "AI Query Access"),         # 0.05 CSPR
}

# Routes that are always free (health, docs, auth, etc.)
FREE_ROUTES = {
    "/health", "/docs", "/openapi.json", "/redoc",
    "/api/v1/auth", "/api/v1/users", "/api/v1/services",
    "/api/v1/marketplace", "/api/v1/agents", "/api/v1/creators",
    "/api/v1/wallet", "/api/v1/payment",
    "/api/v1/session", "/api/v1/conversations",
}

# Estimated cost per chat message for session deduction (before we know real token count)
# Set conservatively - actual deduction happens after AI responds in chat.py
SESSION_ESTIMATED_COST_UNITS = 100_000_000  # 0.1 CSPR per message estimate


class X402PaymentMiddleware(BaseHTTPMiddleware):
    """
    x402 payment enforcement middleware for FastAPI.
    
    Supports two payment modes:
      1. Session Mode: X-Session-Token header → deducts from pre-paid session balance
      2. Per-Request Mode: PAYMENT-SIGNATURE header → settles on-chain for each request
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        
        # Only enforce on POST/GET to protected routes
        if method not in ("POST", "GET"):
            return await call_next(request)
        
        # Check if this route needs payment
        protected_config = self._get_protected_config(path)
        if protected_config is None:
            return await call_next(request)
        
        base_cost_units, description = protected_config
        resource_url = str(request.url)
        
        # ── Mode 1: Session Token ─────────────────────────────────────────────
        session_token = (
            request.headers.get("X-Session-Token") or
            request.headers.get("x-session-token")
        )
        
        if session_token:
            return await self._handle_session_payment(
                request, call_next, session_token, base_cost_units, resource_url, description
            )
        
        # ── Mode 2: Per-Request Payment Signature ─────────────────────────────
        payment_sig_header = (
            request.headers.get("PAYMENT-SIGNATURE") or
            request.headers.get("payment-signature")
        )
        
        if not payment_sig_header:
            # No payment at all → return 402 with session-mode instructions
            logger.info(f"x402: No payment for {path}, returning 402")
            return self._payment_required_response(resource_url, base_cost_units, description)
        
        # Parse the per-request payment payload
        payment_payload = parse_payment_signature_header(payment_sig_header)
        if not payment_payload:
            logger.warning(f"x402: Malformed PAYMENT-SIGNATURE header for {path}")
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Malformed payment signature",
                    "invalidReason": "malformed_payload",
                    "accepts": [build_payment_requirements(resource_url, base_cost_units, description)]
                }
            )
        
        # Extract amount from payload
        accepted = payment_payload.get("accepted", {})
        amount_str = accepted.get("amount", str(base_cost_units))
        
        # Build requirements for settlement
        payment_requirements = build_payment_requirements(
            resource_url=resource_url,
            amount_units=int(amount_str),
            resource_description=description
        )
        
        # Settle the payment via CSPR.cloud facilitator
        logger.info(f"x402: Settling per-request payment for {path}, amount={amount_str} units")
        settle_result = await settle_payment(payment_payload, payment_requirements)
        
        if not settle_result.get("success"):
            reason = settle_result.get("errorReason", "unknown")
            message = settle_result.get("errorMessage", "Payment settlement failed")
            logger.warning(f"x402: Payment failed for {path}: {reason} - {message}")
            return JSONResponse(
                status_code=402,
                content={
                    "error": "Payment settlement failed",
                    "invalidReason": reason,
                    "invalidMessage": message,
                    "accepts": [build_payment_requirements(resource_url, base_cost_units, description)]
                }
            )
        
        # Attach settlement info to request state
        request.state.x402_settled = True
        request.state.x402_mode = "per_request"
        request.state.x402_payer = settle_result.get("payer", "")
        request.state.x402_transaction = settle_result.get("transaction", "")
        request.state.x402_amount_units = int(amount_str)
        
        logger.info(f"x402: Per-request payment settled for {path} | tx={settle_result.get('transaction', '')[:16]}...")
        
        response = await call_next(request)
        response.headers["X-Payment-Transaction"] = settle_result.get("transaction", "")
        response.headers["X-Payment-Network"] = settings.casper_network
        response.headers["X-Payment-Amount"] = amount_str
        response.headers["X-Payment-Mode"] = "per_request"
        
        return response
    
    async def _handle_session_payment(
        self, request, call_next, session_token, base_cost_units, resource_url, description
    ):
        """Handle payment via pre-paid session balance."""
        session = await get_session(session_token)
        
        if session is None:
            logger.info(f"x402: Session token invalid/expired, returning 402")
            return self._payment_required_response(
                resource_url, base_cost_units, description,
                reason="session_expired",
                message="Your payment session has expired. Please start a new session."
            )
        
        # Check if session has enough balance for at least this request
        if session["remaining_units"] < base_cost_units:
            remaining = session["remaining_units"]
            logger.info(
                f"x402: Session {session_token[:12]}... insufficient balance "
                f"(has {remaining}, needs {base_cost_units})"
            )
            return self._payment_required_response(
                resource_url, base_cost_units, description,
                reason="session_balance_depleted",
                message=f"Session balance depleted ({remaining / 1e9:.6f} CSPR remaining). Please add more funds."
            )
        
        # Deduct estimated cost (will be corrected post-response in chat.py for token-based)
        session_info = await deduct_from_session(session_token, base_cost_units)
        if not session_info:
            return self._payment_required_response(
                resource_url, base_cost_units, description,
                reason="session_balance_depleted",
                message="Session balance depleted concurrently. Please add more funds."
            )
        
        # Attach session info to request state for use in route handlers
        request.state.x402_settled = True
        request.state.x402_mode = "session"
        request.state.x402_session_token = session_token
        request.state.x402_payer = session["payer_wallet"]
        request.state.x402_transaction = session["tx_hash"]
        request.state.x402_amount_units = base_cost_units
        request.state.x402_session_remaining = session_info["remaining_units"]
        
        logger.info(
            f"x402: Session payment OK for {request.url.path} | "
            f"token={session_token[:12]}... | remaining={session_info['remaining_units'] / 1e9:.4f} CSPR"
        )
        
        response = await call_next(request)
        
        # Add session balance info to response headers for the frontend
        response.headers["X-Payment-Mode"] = "session"
        response.headers["X-Session-Remaining"] = str(session_info["remaining_units"])
        response.headers["X-Session-Remaining-CSPR"] = f"{session_info['remaining_units'] / 1e9:.6f}"
        response.headers["X-Payment-Network"] = settings.casper_network
        response.headers["X-Payment-Transaction"] = session["tx_hash"]
        
        return response
    
    def _get_protected_config(self, path: str):
        """Returns (cost_units, description) if path is protected, else None."""
        # Check free routes first
        for free in FREE_ROUTES:
            if path.startswith(free):
                return None
        # Check protected routes
        for prefix, config in PROTECTED_ROUTES.items():
            if path.startswith(prefix):
                return config
        return None
    
    def _payment_required_response(
        self, resource_url: str, amount_units: int, description: str,
        reason: str = None, message: str = None
    ) -> JSONResponse:
        """Build a proper 402 Payment Required JSON response."""
        body = build_402_response(resource_url, amount_units, description)
        if reason:
            body["invalidReason"] = reason
        if message:
            body["invalidMessage"] = message
        # Tell the frontend to use session mode
        body["preferSessionMode"] = True
        body["sessionCreateEndpoint"] = "/api/v1/payment/session/create"
        return JSONResponse(
            status_code=402,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Payment-Required": "true",
                "X-Payment-Network": settings.casper_network,
                "X-Payment-Amount": str(amount_units),
            }
        )
