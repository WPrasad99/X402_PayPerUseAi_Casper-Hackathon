"""
PayAI Token (PAIT) — CEP-18 Deployment Guide for Casper Testnet

Since CEP-18 contracts require compiled WASM, this script:
1. Guides you through downloading the pre-compiled cep18.wasm
2. Uses casper-client CLI to deploy it to testnet
3. Fetches and prints the resulting contract package hash

Prerequisites:
  - casper-client installed (see instructions below)
  - Casper Wallet with testnet CSPR (from faucet)
  - Your secret key file exported from Casper Wallet

INSTALL casper-client on Windows (via WSL or use the Docker approach):
  Option A - WSL: sudo apt install casper-client
  Option B - Docker: docker run --rm casplabs/casper-client:latest

OR use the Casper Signer / CSPR.live to deploy via the browser UI.

==============================================================================
RECOMMENDED APPROACH: Use the casper-x402 demo environment
==============================================================================

The casper-x402 GitHub repo provides a pre-deployed testnet CEP-18 contract:
  Contract Package Hash: 3931f6de0e1e861fc1f0946fa73b74a0e503866e605c15f32cfb83dd2160687b

You can use THIS for development. To deploy YOUR OWN token follow steps below.

==============================================================================
Step-by-step deployment using Python + casper-client subprocess
==============================================================================
"""

import subprocess
import sys
import os
import json
import time
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────
TOKEN_NAME = "PayAIToken"
TOKEN_SYMBOL = "PAIT"
TOKEN_DECIMALS = 2               # 2 decimals → 100 base units = 1 PAIT
TOTAL_SUPPLY = "10000000000"     # 100,000,000.00 PAIT total supply

TESTNET_NODE = "https://rpc.testnet.csprcloud.com"
CHAIN_NAME = "casper-test"

# Path to your secret key exported from Casper Wallet
# To export: Casper Wallet → Settings → Export Private Key → save as ed25519/secret_key.pem
SECRET_KEY_PATH = "./my_secret_key.pem"

# Path to the compiled CEP-18 WASM file
# Download from: https://github.com/casper-ecosystem/cep18/releases
WASM_PATH = "./cep18.wasm"

# CSPR.cloud API key for fetching deploy results
CSPR_CLOUD_API_KEY = os.getenv("CSPR_X402_API_KEY", "")

# ─────────────────────────────────────────────────────────────────────────────

def check_prerequisites():
    """Check that required tools and files exist."""
    print("\n📋 Checking prerequisites...")
    
    # Check casper-client
    try:
        result = subprocess.run(["casper-client", "--version"], capture_output=True, text=True)
        print(f"  ✅ casper-client: {result.stdout.strip()}")
    except FileNotFoundError:
        print("  ❌ casper-client not found!")
        print("\n  Install instructions:")
        print("  • WSL/Linux: sudo apt install casper-client")
        print("  • Or download from: https://github.com/casper-network/casper-node/releases")
        print("  • Or use Docker: docker run --rm casplabs/casper-client:latest --version")
        print("\n  ALTERNATIVE: Use the pre-deployed testnet token:")
        print("  CEP18_CONTRACT_PACKAGE_HASH=3931f6de0e1e861fc1f0946fa73b74a0e503866e605c15f32cfb83dd2160687b")
        sys.exit(1)
    
    # Check WASM file
    if not os.path.exists(WASM_PATH):
        print(f"  ❌ WASM file not found at {WASM_PATH}")
        print("\n  Download cep18.wasm:")
        print("  1. Go to: https://github.com/casper-ecosystem/cep18/releases")
        print("  2. Download cep18.wasm from the latest release")
        print("  3. Place it in the scripts/ directory")
        sys.exit(1)
    print(f"  ✅ WASM file found: {WASM_PATH}")
    
    # Check secret key
    if not os.path.exists(SECRET_KEY_PATH):
        print(f"  ❌ Secret key not found at {SECRET_KEY_PATH}")
        print("\n  Export your key from Casper Wallet:")
        print("  1. Open Casper Wallet extension")
        print("  2. Settings → Accounts → ⋮ → Export Private Key")
        print("  3. Save as my_secret_key.pem in scripts/ directory")
        sys.exit(1)
    print(f"  ✅ Secret key found: {SECRET_KEY_PATH}")


def get_account_hash_from_key():
    """Get the account hash from the secret key file."""
    result = subprocess.run(
        ["casper-client", "account-address", "--secret-key", SECRET_KEY_PATH],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ Failed to get account address: {result.stderr}")
        sys.exit(1)
    
    public_key = result.stdout.strip()
    print(f"  📍 Your public key: {public_key}")
    
    # Get account hash
    result2 = subprocess.run(
        ["casper-client", "account-address", "--secret-key", SECRET_KEY_PATH, "--output", "account-hash"],
        capture_output=True, text=True
    )
    account_hash = result2.stdout.strip().replace("account-hash-", "")
    print(f"  📍 Your account hash: {account_hash}")
    return public_key, account_hash


def deploy_cep18_token():
    """Deploy the CEP-18 token to Casper Testnet."""
    print(f"\n🚀 Deploying {TOKEN_NAME} ({TOKEN_SYMBOL}) to {CHAIN_NAME}...")
    print(f"   Total supply: {int(TOTAL_SUPPLY) / (10**TOKEN_DECIMALS):,.{TOKEN_DECIMALS}f} {TOKEN_SYMBOL}")
    
    cmd = [
        "casper-client", "put-deploy",
        "--node-address", TESTNET_NODE,
        "--chain-name", CHAIN_NAME,
        "--secret-key", SECRET_KEY_PATH,
        "--payment-amount", "100000000000",     # 100 CSPR for gas
        "--session-path", WASM_PATH,
        "--session-arg", f"name:string='{TOKEN_NAME}'",
        "--session-arg", f"symbol:string='{TOKEN_SYMBOL}'",
        "--session-arg", f"decimals:u8={TOKEN_DECIMALS}",
        "--session-arg", f"total_supply:u256='{TOTAL_SUPPLY}'",
        "--session-arg", "enable_mint_burn:bool=true",   # Allow future minting
    ]
    
    print(f"\n  Running deploy command...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Deploy failed:\n{result.stderr}")
        sys.exit(1)
    
    output = json.loads(result.stdout)
    deploy_hash = output.get("deploy_hash") or output.get("result", {}).get("deploy_hash", "")
    
    if not deploy_hash:
        print(f"❌ No deploy hash in response: {result.stdout}")
        sys.exit(1)
    
    print(f"\n  ✅ Deploy submitted!")
    print(f"  📦 Deploy hash: {deploy_hash}")
    print(f"  🔗 Track on explorer: https://testnet.cspr.live/deploy/{deploy_hash}")
    
    return deploy_hash


def wait_for_deploy(deploy_hash: str, max_wait: int = 120):
    """Poll until the deploy is finalized."""
    print(f"\n⏳ Waiting for deploy to finalize (up to {max_wait}s)...")
    
    for attempt in range(max_wait // 5):
        time.sleep(5)
        
        result = subprocess.run(
            ["casper-client", "get-deploy", "--node-address", TESTNET_NODE, deploy_hash],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            exec_results = data.get("result", {}).get("execution_results", [])
            if exec_results:
                result_type = list(exec_results[0].get("result", {}).keys())
                if "Success" in result_type:
                    print(f"  ✅ Deploy succeeded after {(attempt+1)*5}s!")
                    return data
                elif "Failure" in result_type:
                    error = exec_results[0]["result"]["Failure"]["error_message"]
                    print(f"  ❌ Deploy failed: {error}")
                    sys.exit(1)
        
        print(f"  ... still waiting ({(attempt+1)*5}s)")
    
    print(f"  ⚠️  Timed out waiting for deploy. Check manually:")
    print(f"  https://testnet.cspr.live/deploy/{deploy_hash}")
    return None


def get_contract_package_hash(account_hash: str, deploy_hash: str):
    """Fetch the contract package hash from the account's named keys."""
    print(f"\n🔍 Fetching contract package hash...")
    
    # Use CSPR.cloud API to get named keys
    api_url = f"https://api.testnet.csprcloud.com/accounts/account-hash-{account_hash}"
    
    try:
        headers = {"authorization": CSPR_CLOUD_API_KEY, "accept": "application/json"}
        resp = httpx.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        named_keys = data.get("named_keys", [])
        for key in named_keys:
            if TOKEN_NAME.lower().replace(" ", "_") in key.get("name", "").lower():
                pkg_hash = key.get("key", "").replace("hash-", "")
                print(f"  ✅ Found contract: {key['name']}")
                print(f"  📦 Package hash: {pkg_hash}")
                return pkg_hash
    except Exception as e:
        print(f"  ⚠️  Could not auto-fetch via API: {e}")
    
    # Fallback: use casper-client
    result = subprocess.run(
        ["casper-client", "query-global-state",
         "--node-address", TESTNET_NODE,
         "--state-root-hash", "latest",
         "--key", f"account-hash-{account_hash}"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        data = json.loads(result.stdout)
        named_keys = data.get("result", {}).get("stored_value", {}).get("Account", {}).get("named_keys", [])
        for key in named_keys:
            if "cep18" in key.get("name", "").lower() or TOKEN_SYMBOL.lower() in key.get("name", "").lower():
                pkg_hash = key.get("key", "").replace("hash-", "")
                print(f"  ✅ Package hash: {pkg_hash}")
                return pkg_hash
    
    print(f"  ⚠️  Could not auto-detect package hash.")
    print(f"  Manually check: https://testnet.cspr.live/account/{account_hash}")
    return None


def save_config(account_hash: str, package_hash: str):
    """Print the .env variables to set."""
    print("\n" + "="*60)
    print("✅ DEPLOYMENT COMPLETE!")
    print("="*60)
    print("\nAdd these to your backend/.env file:")
    print()
    print(f"CEP18_CONTRACT_PACKAGE_HASH={package_hash}")
    print(f"PLATFORM_ACCOUNT_HASH=00{account_hash}")   # 00 prefix = ED25519 account hash format
    print(f"CEP18_TOKEN_NAME={TOKEN_NAME}")
    print(f"CEP18_TOKEN_SYMBOL={TOKEN_SYMBOL}")
    print(f"CEP18_TOKEN_DECIMALS={TOKEN_DECIMALS}")
    print()
    print("Also add to your frontend .env:")
    print(f"VITE_CEP18_CONTRACT_HASH={package_hash}")
    print(f"VITE_CASPER_NETWORK=casper:casper-test")
    print()
    print(f"🔗 View your token: https://testnet.cspr.live/contract-package/{package_hash}")
    print()
    print("Next step: Fund users with PAIT tokens for testing")
    print(f"  Use: casper-client put-deploy ... transfer entry point")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════╗")
    print("║  PayAI Token (PAIT) — CEP-18 Deployment Script       ║")
    print("║  Target: Casper Testnet (casper-test)                ║")
    print("╚══════════════════════════════════════════════════════╝")
    
    print("\n⚠️  BEFORE RUNNING THIS SCRIPT:")
    print("  1. Install Casper Wallet: https://casperwallet.io")
    print("  2. Switch to Testnet in wallet settings")
    print("  3. Get testnet CSPR: https://testnet.cspr.live/tools/faucet")
    print("  4. Export your secret key (Settings → Export Private Key)")
    print("  5. Download cep18.wasm from https://github.com/casper-ecosystem/cep18/releases")
    print()
    
    choice = input("Proceed with deployment? [y/N]: ").strip().lower()
    if choice != 'y':
        print("\nAborted. Using pre-deployed testnet token:")
        print("CEP18_CONTRACT_PACKAGE_HASH=3931f6de0e1e861fc1f0946fa73b74a0e503866e605c15f32cfb83dd2160687b")
        sys.exit(0)
    
    check_prerequisites()
    public_key, account_hash = get_account_hash_from_key()
    deploy_hash = deploy_cep18_token()
    wait_for_deploy(deploy_hash)
    package_hash = get_contract_package_hash(account_hash, deploy_hash)
    
    if package_hash:
        save_config(account_hash, package_hash)
    else:
        print("\n⚠️  Please manually find the contract package hash on the explorer")
        print(f"  https://testnet.cspr.live/account/{account_hash}")
