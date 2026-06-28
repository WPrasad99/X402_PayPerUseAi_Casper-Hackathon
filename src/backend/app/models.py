"""
Pydantic v2 models representing the API Request/Response schema.
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

class ServiceOut(BaseModel):
    id: str
    name: str  
    description: str
    price_input_motes: int
    price_output_motes: int
    price_cspr: Optional[float] = 0.0
    price_motes: Optional[int] = 0
    example_prompt: str
    provider: Optional[str] = None
    model: Optional[str] = None

class PaymentInfoOut(BaseModel):
    service_id: str
    app_id: int
    contract_address: str
    amount_motes: int
    amount_cspr: float
    qr_code_base64: str
    instructions: List[str]

class InitiatePaymentIn(BaseModel):
    service_id: str
    wallet_address: str
    prompt: str
    
    @field_validator('wallet_address')
    @classmethod
    def validate_casper_address(cls, v: str) -> str:
        """Validates standard Casper hex public key (66 or 68 chars) or account hash."""
        # Casper public keys start with 01 (Ed25519) or 02 (Secp256k1) and are hex
        v_clean = v.strip().lower()
        if len(v_clean) not in [64, 66, 68] or not all(c in '0123456789abcdef' for c in v_clean):
            raise ValueError("Invalid Casper address format")
        return v

class InitiatePaymentOut(BaseModel):
    session_id: str
    expires_in_seconds: int
    message: str

class QueryIn(BaseModel):
    session_id: str
    tx_group_id: str

class QueryOut(BaseModel):
    status: str
    ai_response: str
    tx_verified: bool
    service_used: str
    tokens_used: int
  
class ErrorOut(BaseModel):
    error: str
    detail: str
