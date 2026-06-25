"""
Application configuration using pydantic-settings.
Migrated from Algorand → Casper Network + x402 Protocol.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = "sk-placeholder"
    
    # Groq
    groq_api_key: str = ""
    
    # Google Gemini
    gemini_api_key: str = ""
    
    # HuggingFace
    hf_api_key: str = ""
    
    # ── Casper Network ────────────────────────────────────────
    # Platform receiver: account hash (00<64hex>) derived from the public key
    platform_account_hash: str = ""
    # Platform public key: needed by frontend to build CLPublicKey for native transfers
    # Format: "02<66hex>" (Secp256k1) or "01<64hex>" (Ed25519)
    platform_public_key: str = ""
    # Platform PRIVATE key hex (32 bytes = 64 chars) — used to sign outgoing creator payouts
    # Export from Casper Wallet: Settings → Account → Export Private Key
    platform_secret_key_hex: str = ""
    casper_network: str = "casper:casper-test"          # CAIP-2 identifier for Casper Testnet
    casper_node_rpc_url: str = "https://rpc.testnet.csprcloud.com"
    
    # ── CSPR.cloud x402 Facilitator ──────────────────────────
    cspr_x402_facilitator_url: str = "https://x402-facilitator.cspr.cloud"
    cspr_x402_api_key: str = ""                         # Get from cspr.build console
    
    # ── CEP-18 Token (PayAI Token = PAIT) (OPTIONAL) ─────────
    # If using native CSPR, this can be empty
    cep18_contract_package_hash: str = ""
    cep18_token_name: str = "CSPR"
    cep18_token_symbol: str = "CSPR"
    cep18_token_decimals: int = 9                       # CSPR has 9 decimals
    cep18_token_version: str = "1"

    
    # ── x402 Payment Settings ────────────────────────────────
    # Cost per AI token in CEP-18 base units (2 decimals → 100 = 1 PAIT)
    # Example: 1 base unit = 0.01 PAIT per AI token output
    cost_per_ai_token_units: int = 1                    # base units per AI output token
    min_payment_units: int = 100                        # Minimum 1 PAIT per request
    max_timeout_seconds: int = 300                      # 5 minutes for payment validity
    
    # ── PostgreSQL Database ───────────────────────────────────
    database_url: str = "postgresql://postgres:1234@localhost:5432/payperai"
    
    # ── App ──────────────────────────────────────────────────
    app_secret_key: str = "replace-with-a-long-random-string-minimum-32-chars"
    
    # ── Marketplace ──────────────────────────────────────────
    api_key_encryption_secret: str = ""                 # 32-byte hex key for AES-256-GCM
    marketplace_fee_pct: int = 10                       # 10% platform fee, 90% to creators
    cors_origins: str = "http://localhost:5173,http://localhost:4173,https://pay-per-use-ai.vercel.app"

    platform_base_url: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
