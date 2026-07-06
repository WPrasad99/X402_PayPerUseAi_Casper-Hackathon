"""
Casper On-Chain Transaction Service
Broadcasts a signed Casper Deploy and polls for finality.

Key facts about CSPR.cloud:
- RPC endpoint: <node-url>/rpc  (not just the base URL)
- Auth header: 'authorization: <api_key>'  (no 'Bearer ' prefix)
- account_put_deploy params: {"deploy": <deploy_object>}
  where <deploy_object> is the inner deploy dict (not the whole deployToJson output)
"""
import asyncio
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _rpc_url(base_url: str) -> str:
    """Ensure the RPC URL ends with /rpc."""
    base = base_url.rstrip("/")
    if not base.endswith("/rpc"):
        base = base + "/rpc"
    return base


def _rpc_headers() -> dict:
    """Return auth headers for CSPR.cloud RPC.
    
    CSPR.cloud requires:  authorization: <api_key>  (no Bearer prefix)
    """
    headers = {"Content-Type": "application/json"}
    if settings.cspr_x402_api_key:
        headers["authorization"] = settings.cspr_x402_api_key
    return headers


def _unwrap_deploy(deploy_json: dict) -> dict:
    """
    casper-js-sdk v2 DeployUtil.deployToJson() wraps the deploy in:
        { "deploy": { "hash": ..., "header": ..., ... } }
    
    The Casper RPC account_put_deploy expects params: {"deploy": <inner_deploy>}
    So we must send deploy_json["deploy"], not deploy_json itself.
    """
    if "deploy" in deploy_json:
        return deploy_json["deploy"]
    # Already unwrapped
    return deploy_json


async def broadcast_and_confirm(
    rpc_url: str,
    deploy_json: dict,
    max_wait_seconds: int = 90,
    poll_interval_seconds: int = 3,
) -> dict:
    """
    Broadcast a signed Deploy to the Casper RPC node and wait for it to be executed.

    Args:
        rpc_url: Base node URL (e.g. https://node.testnet.cspr.cloud)
        deploy_json: The full deploy JSON from casper-js-sdk deployToJson()
        max_wait_seconds: How long to poll for finality
        poll_interval_seconds: Polling interval

    Returns:
        dict with keys: deploy_hash, success, error_message (if failed)
    """
    url = _rpc_url(rpc_url)
    headers = _rpc_headers()

    # Unwrap the deploy (casper-js-sdk wraps it in {"deploy": {...}})
    inner_deploy = _unwrap_deploy(deploy_json)
    
    logger.info("Broadcasting deploy to %s", url)
    logger.debug("Deploy inner keys: %s", list(inner_deploy.keys()) if isinstance(inner_deploy, dict) else type(inner_deploy))

    # ── Step 1: Submit the deploy ──────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            put_resp = await client.post(
                url,
                json={
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "account_put_deploy",
                    "params": {"deploy": inner_deploy},
                },
                headers=headers,
            )
            logger.info("account_put_deploy response status: %s", put_resp.status_code)
            logger.debug("account_put_deploy raw response: %s", put_resp.text[:500])

            if put_resp.status_code == 401:
                return {"success": False, "error_message": "RPC auth failed: " + put_resp.text[:200]}

            if not put_resp.text.strip():
                return {"success": False, "error_message": "RPC returned empty response. Check node URL and auth."}

            put_data = put_resp.json()

    except Exception as exc:
        logger.error("Failed to broadcast deploy: %s", exc)
        return {"success": False, "error_message": f"Broadcast error: {exc}"}

    if "error" in put_data:
        err = put_data["error"]
        msg = err.get("message", str(err))
        logger.error("RPC rejected deploy: %s", msg)
        return {"success": False, "error_message": f"Deploy rejected: {msg}"}

    deploy_hash = put_data.get("result", {}).get("deploy_hash")
    if not deploy_hash:
        logger.error("No deploy_hash in response: %s", put_data)
        return {"success": False, "error_message": f"No deploy_hash in RPC response: {put_data}"}

    logger.info("Deploy broadcast OK: %s", deploy_hash)

    # ── Step 2: Poll for execution result ─────────────────────────────────
    # For Testnet / fast UX, we don't want to block the UI for 90 seconds. 
    # Since the node accepted it into the mempool, we assume it will eventually execute.
    # We poll just a few times (e.g. 9 seconds) and if it hasn't executed, we return pending success.
    
    elapsed = 0
    poll_limit = min(max_wait_seconds, 9)
    
    while elapsed < poll_limit:
        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                info_resp = await client.post(
                    url,
                    json={
                        "id": 2,
                        "jsonrpc": "2.0",
                        "method": "info_get_deploy",
                        "params": {"deploy_hash": deploy_hash},
                    },
                    headers=headers
                )
                if info_resp.status_code != 200:
                    continue

                info_data = info_resp.json()
                res = info_data.get("result", {})
                exec_results = res.get("execution_results", [])

                if exec_results:
                    first_res = exec_results[0].get("result", {})
                    if "Success" in first_res:
                        logger.info("Deploy executed successfully: %s", deploy_hash)
                        return {"success": True, "deploy_hash": deploy_hash, "status": "confirmed"}
                    if "Failure" in first_res:
                        err_msg = first_res["Failure"].get("error_message", "Unknown failure")
                        logger.error("Deploy failed on-chain: %s", err_msg)
                        return {"success": False, "error_message": f"On-chain execution failed: {err_msg}"}

        except Exception as exc:
            logger.warning("Polling error: %s", exc)

    logger.info("Deploy is pending in mempool. Returning early success for UX: %s", deploy_hash)
    return {"success": True, "deploy_hash": deploy_hash, "status": "pending"}
