"""
Casper Platform Payout Service
Signs and broadcasts a native CSPR transfer from the platform wallet to a creator wallet.
Used exclusively for creator withdrawal payouts.

Requires PLATFORM_SECRET_KEY_HEX in .env — the 64-char hex private key for the platform wallet.
The creator can export this from Casper Wallet: Settings → Account → Export Private Key.
"""
import time
import json
import asyncio
import logging
import hashlib
import struct
from typing import Optional
from app.config import settings
from app.services.casper_onchain import broadcast_and_confirm

logger = logging.getLogger(__name__)

TRANSFER_GAS_MOTES = 100_000_000     # 0.1 CSPR gas payment for native transfer
MIN_PAYOUT_MOTES   = 2_500_000_000   # 2.5 CSPR minimum (Casper network requirement)


# ── Casper Deploy Builder (pure Python, no pycspr dependency for serialization) ──

def _u64_le(value: int) -> bytes:
    return struct.pack("<Q", value)

def _u32_le(value: int) -> bytes:
    return struct.pack("<I", value)

def _u8(value: int) -> bytes:
    return bytes([value])

def _encode_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return _u32_le(len(encoded)) + encoded

def _encode_bytes(b: bytes) -> bytes:
    return _u32_le(len(b)) + b


def _cl_value_u512(value: int) -> dict:
    """Encode a U512 value as a CL value for deploy args."""
    # U512 is encoded as variable-length little-endian
    if value == 0:
        raw = bytes([0])
    else:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "little")
    
    return {
        "cl_type": "U512",
        "bytes": raw.hex(),
        "parsed": str(value)
    }


def _cl_value_u64(value: int) -> dict:
    return {
        "cl_type": "U64",
        "bytes": _u64_le(value).hex(),
        "parsed": value
    }


def _cl_value_option_u64(value: Optional[int]) -> dict:
    if value is None:
        return {
            "cl_type": {"Option": "U64"},
            "bytes": "00",
            "parsed": None
        }
    return {
        "cl_type": {"Option": "U64"},
        "bytes": "01" + _u64_le(value).hex(),
        "parsed": value
    }


def _cl_value_public_key(public_key_hex: str) -> dict:
    """Encode a Casper PublicKey as CL bytes."""
    # PublicKey encoding: 1-byte tag + key bytes
    # Tag 01 = Ed25519, Tag 02 = Secp256k1
    if public_key_hex.startswith("01"):
        tag = "01"
        key_bytes = public_key_hex[2:]
    elif public_key_hex.startswith("02"):
        tag = "02"
        key_bytes = public_key_hex[2:]
    else:
        raise ValueError(f"Unknown public key prefix: {public_key_hex[:4]}")
    return {
        "cl_type": "PublicKey",
        "bytes": tag + key_bytes,
        "parsed": public_key_hex
    }


def _build_transfer_deploy(
    from_public_key_hex: str,
    to_public_key_hex: str,
    amount_motes: int,
    chain_name: str = "casper-test",
    ttl_ms: int = 1_800_000,  # 30 minutes
    gas_price: int = 1,
    transfer_id: Optional[int] = None,
) -> dict:
    """
    Build the unsigned Transfer deploy dict that mirrors the Casper RPC format.
    This structure matches what casper-js-sdk's deployToJson() produces.
    """
    timestamp_ms = int(time.time() * 1000)
    ttl_str = f"{ttl_ms // 60000}m"
    if transfer_id is None:
        transfer_id = timestamp_ms

    deploy = {
        "hash": "",  # Will be filled after serialization
        "header": {
            "account": from_public_key_hex,
            "timestamp": _ms_to_iso(timestamp_ms),
            "ttl": ttl_str,
            "gas_price": gas_price,
            "body_hash": "",  # Will be filled
            "dependencies": [],
            "chain_name": chain_name,
        },
        "payment": {
            "ModuleBytes": {
                "module_bytes": "",
                "args": [
                    ["amount", _cl_value_u512(TRANSFER_GAS_MOTES)]
                ]
            }
        },
        "session": {
            "Transfer": {
                "args": [
                    ["amount", _cl_value_u512(amount_motes)],
                    ["target", _cl_value_public_key(to_public_key_hex)],
                    ["id", _cl_value_option_u64(transfer_id)],
                ]
            }
        },
        "approvals": []
    }
    return deploy


def _ms_to_iso(ms: int) -> str:
    import datetime
    dt = datetime.datetime.utcfromtimestamp(ms / 1000.0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ── pycspr-based signing ──────────────────────────────────────────────────────

def _sign_and_build_deploy(
    from_private_key_hex: str,
    to_public_key_hex: str,
    amount_motes: int,
    chain_name: str,
) -> dict:
    """
    Use pycspr to properly build, hash, and sign a native Transfer deploy.
    Returns the full signed deploy JSON ready for account_put_deploy RPC.
    """
    import pycspr
    from pycspr.types.crypto import KeyAlgorithm

    # --- Load platform private key ---
    pvk_bytes = bytes.fromhex(from_private_key_hex.strip())
    
    # Determine algorithm from platform public key prefix
    if settings.platform_public_key.startswith("02"):
        algo = KeyAlgorithm.SECP256K1
    else:
        algo = KeyAlgorithm.ED25519

    # Create key objects
    private_key = pycspr.factory.create_private_key(algo, pvk_bytes)
    sender_pub  = private_key.as_public_key()

    # Recipient public key
    recipient = pycspr.factory.create_public_key_from_hex(to_public_key_hex)

    # Deploy params
    deploy_params = pycspr.create_deploy_params(
        account=sender_pub,
        chain_name=chain_name,
        gas_price=1,
        ttl="30m",
    )

    # Build transfer deploy
    deploy = pycspr.factory.create_transfer(
        params=deploy_params,
        amount=amount_motes,
        target=recipient,
        correlation_id=int(time.time()),
    )

    # Sign
    deploy.approve(private_key)

    # Serialize to JSON dict (casper-js-sdk compatible format)
    deploy_json = pycspr.serialisation.to_json(deploy)
    return deploy_json


# ── Main payout function ──────────────────────────────────────────────────────

async def send_creator_payout(
    creator_public_key: str,
    amount_motes: int,
) -> dict:
    """
    Sign and broadcast a native CSPR transfer from the platform wallet to a creator.

    Args:
        creator_public_key: Creator's Casper public key (01xxx or 02xxx hex)
        amount_motes: Amount in motes (1 CSPR = 1,000,000,000 motes)

    Returns:
        {
            success: bool,
            deploy_hash: str,
            explorer_url: str,
            amount_motes: int,
            amount_cspr: float,
            error: str  (only if success=False)
        }
    """
    # --- Guards ---
    if not settings.platform_secret_key_hex:
        logger.error("PLATFORM_SECRET_KEY_HEX not set in .env")
        return {
            "success": False,
            "error": (
                "Platform payout key not configured. "
                "Add PLATFORM_SECRET_KEY_HEX to your .env file. "
                "Export the private key for wallet 02024370ec... from Casper Wallet."
            ),
            "deploy_hash": "",
            "explorer_url": "",
        }

    if amount_motes < MIN_PAYOUT_MOTES:
        return {
            "success": False,
            "error": (
                f"Amount too small. Minimum payout on Casper is "
                f"{MIN_PAYOUT_MOTES / 1e9:.1f} CSPR ({MIN_PAYOUT_MOTES:,} motes). "
                f"Keep accumulating earnings until you reach this threshold."
            ),
            "deploy_hash": "",
            "explorer_url": "",
        }

    chain_name = settings.casper_network.replace("casper:", "")  # "casper-test"

    logger.info(
        "Initiating payout: %.4f CSPR (%d motes) → %s...",
        amount_motes / 1e9, amount_motes, creator_public_key[:20]
    )

    # --- Build + sign deploy ---
    try:
        loop = asyncio.get_event_loop()
        deploy_json = await loop.run_in_executor(
            None,
            _sign_and_build_deploy,
            settings.platform_secret_key_hex,
            creator_public_key,
            amount_motes,
            chain_name,
        )
    except ImportError:
        return {
            "success": False,
            "error": "pycspr is not installed. Run: pip install pycspr",
            "deploy_hash": "",
            "explorer_url": "",
        }
    except Exception as e:
        logger.error("Failed to build/sign deploy: %s", e, exc_info=True)
        return {
            "success": False,
            "error": f"Failed to build transfer deploy: {e}",
            "deploy_hash": "",
            "explorer_url": "",
        }

    # --- Broadcast + confirm via existing RPC service ---
    try:
        result = await broadcast_and_confirm(
            rpc_url=settings.casper_node_rpc_url,
            deploy_json=deploy_json,
            max_wait_seconds=90,
            poll_interval_seconds=4,
        )
    except Exception as e:
        logger.error("Failed to broadcast payout deploy: %s", e, exc_info=True)
        return {
            "success": False,
            "error": f"Failed to broadcast transfer: {e}",
            "deploy_hash": "",
            "explorer_url": "",
        }

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error_message", "On-chain transfer failed"),
            "deploy_hash": result.get("deploy_hash", ""),
            "explorer_url": "",
        }

    deploy_hash = result["deploy_hash"]
    explorer_url = f"https://testnet.cspr.live/deploy/{deploy_hash}"

    logger.info(
        "Payout confirmed: %s | %.4f CSPR → %s",
        deploy_hash, amount_motes / 1e9, creator_public_key[:20]
    )

    return {
        "success": True,
        "deploy_hash": deploy_hash,
        "explorer_url": explorer_url,
        "amount_motes": amount_motes,
        "amount_cspr": amount_motes / 1_000_000_000,
        "status": result.get("status", "confirmed"),
    }
