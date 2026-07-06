"""
FastAPI application core — Casper Network + x402 Edition.
Removed: Algorand event listener, refund loop, SIWA auth
Added: x402 payment middleware, Casper wallet support
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import asyncio
import os

from app.config import settings
from app.database import init_db
from app.routes import services, payment, query, chat, wallet, image, marketplace, users
from app.routes.session import router as session_router
from app.routes.auth import router as auth_router
from app.routes.creators import router as creators_router
from app.routes.agents import router as agents_router
from app.core.limiter import limiter
from app.middleware.x402_middleware import X402PaymentMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events spanning the duration of the App."""
    await init_db()
    print("PayPerAI Backend running — Casper Network + x402 Edition")
    print(f"Network: {settings.casper_network}")
    print(f"Facilitator: {settings.cspr_x402_facilitator_url}")
    print(f"CEP-18 Token: {settings.cep18_token_symbol} ({settings.cep18_token_name})")
    print(f"Platform Account: {settings.platform_account_hash[:20] if settings.platform_account_hash else 'NOT SET'}...")
    yield
    
    # Close database pool
    from app.database import close_pool
    await close_pool()


app = FastAPI(
    title="PayPerAI — Casper x402 AI API",
    version="4.0.0",
    description="Pay-per-use AI platform powered by Casper Network and x402 protocol",
    docs_url="/docs",
    lifespan=lifespan
)

# Parse origins from settings
origins = [org.strip() for org in settings.cors_origins.split(",") if org.strip()]
for default_org in ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"]:
    if default_org not in origins:
        origins.append(default_org)

# ── x402 Payment Middleware ─────────────────────────────────
app.add_middleware(X402PaymentMiddleware)

# ── Security + Logging Middleware ───────────────────────────
@app.middleware("http")
async def security_and_log_middleware(request: Request, call_next):
    """Security headers and request logging."""
    print(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Server"] = "PayPerAI-Casper"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "connect-src 'self' https://x402-facilitator.cspr.cloud https://api.cspr.cloud https://rpc.testnet.csprcloud.com; "
        "script-src 'self' 'unsafe-inline'"
    )
    return response

# ── CORS Middleware (MUST BE LAST TO RUN FIRST) ─────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "PAYMENT-SIGNATURE"],
    expose_headers=["X-Payment-Transaction", "X-Payment-Network", "X-Payment-Amount"]
)

# ── Rate Limiter ─────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/")
async def root():
    return {
        "message": "PayPerAI Backend — Casper x402 Edition",
        "version": "4.0.0",
        "architecture": "Casper Network + x402 Protocol",
        "network": settings.casper_network,
        "facilitator": settings.cspr_x402_facilitator_url,
        "token": settings.cep18_token_symbol,
        "docs": "/docs",
        "health": "/health"
    }


# ── Auth Routes ─────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")

# ── Feature Routes ──────────────────────────────────────────
app.include_router(services.router, prefix="/api/v1")
app.include_router(payment.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(wallet.router, prefix="/api/v1")
app.include_router(image.router, prefix="/api/v1")
app.include_router(marketplace.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

# ── Session Info Route ─────────────────────────────────────
app.include_router(session_router, prefix="/api/v1")

# ── Marketplace Routes ──────────────────────────────────────
app.include_router(creators_router, prefix="/api/v1/creators")
app.include_router(agents_router, prefix="/api/v1/agents")

# ── Static Files ────────────────────────────────────────────
os.makedirs("static/nfts", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "4.0.0",
        "architecture": "casper+x402",
        "database": "postgresql",
        "network": settings.casper_network,
        "token": settings.cep18_token_symbol,
        "contract_hash": settings.cep18_contract_package_hash[:16] + "..." if settings.cep18_contract_package_hash else "NOT_SET",
        "platform_account": settings.platform_account_hash[:20] + "..." if settings.platform_account_hash else "NOT_SET",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
