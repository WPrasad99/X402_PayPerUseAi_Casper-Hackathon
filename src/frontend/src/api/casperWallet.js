import { CLPublicKey, DeployUtil } from 'casper-js-sdk';

/**
 * Casper Wallet Connector
 * Handles all interactions with the Casper Wallet browser extension.
 * 
 * Install Casper Wallet: https://casperwallet.io
 * 
 * The Casper Wallet injects window.CasperWalletProvider into the browser.
 * We use it to:
 *  1. Connect / disconnect wallet
 *  2. Get the active account (public key + account hash)
 *  3. Sign EIP-712 typed data for x402 payments
 */

// ── Wallet State ──────────────────────────────────────────────────────────────
let walletProvider = null;
let _connectionListeners = [];

// ── Provider Initialization ───────────────────────────────────────────────────

/**
 * Get or initialize the Casper Wallet provider.
 * Returns null if the extension is not installed.
 */
export function getCasperWalletProvider() {
  if (walletProvider) return walletProvider;
  
  // The extension injects window.CasperWalletProvider
  if (typeof window !== 'undefined' && window.CasperWalletProvider) {
    walletProvider = window.CasperWalletProvider();
    return walletProvider;
  }
  
  return null;
}

/**
 * Check if the Casper Wallet extension is installed.
 */
export function isCasperWalletInstalled() {
  return typeof window !== 'undefined' && typeof window.CasperWalletProvider === 'function';
}

// ── Connection ────────────────────────────────────────────────────────────────

/**
 * Connect to the Casper Wallet.
 * Opens the wallet popup asking the user to approve the connection.
 * 
 * @returns {Promise<{publicKey: string, accountHash: string}>}
 */
export async function connectCasperWallet() {
  const provider = getCasperWalletProvider();
  
  if (!provider) {
    throw new Error(
      'Casper Wallet is not installed. ' +
      'Please install it from https://casperwallet.io'
    );
  }
  
  try {
    // Request connection — this opens the Casper Wallet popup
    const isConnected = await provider.requestConnection();
    
    if (!isConnected) {
      throw new Error('User rejected the wallet connection request.');
    }
    
    // Get the active account details
    const account = await getActiveAccount();
    return account;
    
  } catch (error) {
    if (error.message?.includes('already pending')) {
      throw new Error('A wallet connection request is already pending. Check the extension popup.');
    }
    throw error;
  }
}

/**
 * Disconnect from the Casper Wallet.
 */
export async function disconnectCasperWallet() {
  const provider = getCasperWalletProvider();
  if (provider) {
    try {
      await provider.disconnectFromSite();
    } catch (e) {
      console.warn('Disconnect error (may already be disconnected):', e);
    }
  }
  walletProvider = null;
}

// ── Account Info ──────────────────────────────────────────────────────────────

/**
 * Get the currently active Casper account.
 * 
 * @returns {Promise<{publicKey: string, accountHash: string, isConnected: boolean}>}
 */
export async function getActiveAccount() {
  const provider = getCasperWalletProvider();
  
  if (!provider) {
    return { publicKey: null, accountHash: null, isConnected: false };
  }
  
  try {
    const isConnected = await provider.isConnected();
    if (!isConnected) {
      return { publicKey: null, accountHash: null, isConnected: false };
    }
    
    const activeKey = await provider.getActivePublicKey();
    if (!activeKey) {
      return { publicKey: null, accountHash: null, isConnected: false };
    }
    
    // Convert public key to account hash
    const accountHash = publicKeyToAccountHash(activeKey);
    
    return {
      publicKey: activeKey,
      accountHash,
      isConnected: true
    };
  } catch (error) {
    console.error('Failed to get active account:', error);
    return { publicKey: null, accountHash: null, isConnected: false };
  }
}

/**
 * Convert a Casper public key to account-hash format.
 * Public key format: "01<64 hex>" (ED25519) or "02<66 hex>" (SECP256K1)
 * Account hash format: "00<64 hex>" for display, but we let the backend handle this.
 * 
 * Note: The actual account hash derivation requires hashing on-chain.
 * For display purposes we use the public key prefix.
 * The backend and facilitator accept public keys directly.
 */
export function publicKeyToAccountHash(publicKey) {
  // The public key itself can be used as an identifier in our app.
  // Proper account hash derivation: blake2b(algorithm_bytes + public_key_bytes)
  // For x402 payloads, the facilitator derives this from the signature.
  // We return a display-friendly version here.
  if (!publicKey) return null;
  
  // Store as-is; the x402 client handles proper formatting
  return publicKey;
}

// ── EIP-712 Signing for x402 ──────────────────────────────────────────────────

/**
 * Sign an x402 TransferAuthorization using EIP-712 typed data.
 * This is the core signing operation for x402 payments.
 * 
 * @param {Object} authorizationData - The transfer authorization to sign
 * @param {string} authorizationData.from - Payer account hash (00<64hex>)
 * @param {string} authorizationData.to - Payee account hash (00<64hex>)
 * @param {string} authorizationData.value - Amount in base units (string)
 * @param {string} authorizationData.validAfter - Unix timestamp string
 * @param {string} authorizationData.validBefore - Unix timestamp string
 * @param {string} authorizationData.nonce - 32-byte hex nonce (64 chars)
 * @param {Object} domainData - EIP-712 domain (name, version, verifyingContract)
 * 
 * @returns {Promise<{signature: string, publicKey: string}>}
 */
export async function signX402Authorization(authorizationData, domainData) {
  const provider = getCasperWalletProvider();
  
  if (!provider) {
    throw new Error('Casper Wallet is not installed');
  }

  const eip712DomainTypes = [
    { name: 'name', type: 'string' },
    { name: 'version', type: 'string' }
  ];
  
  const isNativeCasper = domainData.contractHash === 'casper';
  
  const domainObj = {
    name: isNativeCasper ? 'casper' : domainData.name,
    version: isNativeCasper ? '1' : domainData.version
  };

  if (domainData.contractHash && !isNativeCasper) {
    eip712DomainTypes.push({ name: 'verifyingContract', type: 'bytes32' });
    domainObj.verifyingContract = domainData.contractHash;
  }

  const formatBytes32 = (hash) => {
    if (hash && hash.length === 66 && hash.startsWith('00')) {
      return hash.substring(2);
    }
    return hash;
  };

  // Build the EIP-712 typed data structure
  const typedData = {
    types: {
      EIP712Domain: eip712DomainTypes,
      TransferAuthorization: [
        { name: 'from', type: 'bytes32' },
        { name: 'to', type: 'bytes32' },
        { name: 'value', type: 'uint256' },
        { name: 'validAfter', type: 'uint256' },
        { name: 'validBefore', type: 'uint256' },
        { name: 'nonce', type: 'bytes32' },
      ],
    },
    primaryType: 'TransferAuthorization',
    domain: domainObj,
    message: {
      from: formatBytes32(authorizationData.from),
      to: formatBytes32(authorizationData.to),
      value: authorizationData.value,
      validAfter: authorizationData.validAfter,
      validBefore: authorizationData.validBefore,
      nonce: authorizationData.nonce,
    },
  };
  
  try {
    // Casper Wallet signs EIP-712 typed data
    const signResult = await provider.signMessage(
      JSON.stringify(typedData),
      await provider.getActivePublicKey()
    );
    
    if (!signResult?.signature) {
      throw new Error('Signing failed: no signature returned from Casper Wallet');
    }

    let hexSignature = signResult.signature;
    if (hexSignature instanceof Uint8Array) {
      hexSignature = Array.from(hexSignature).map(b => b.toString(16).padStart(2, '0')).join('');
    } else if (typeof hexSignature === 'object' && hexSignature !== null) {
      // Fallback in case it's a generic object but acts like a buffer/array
      hexSignature = Array.from(Object.values(hexSignature)).map(b => Number(b).toString(16).padStart(2, '0')).join('');
    }
    
    return {
      signature: hexSignature,
      publicKey: await provider.getActivePublicKey()
    };
    
  } catch (error) {
    if (error.message?.includes('User rejected') || error.message?.includes('cancelled')) {
      throw new Error('You rejected the payment signing request.');
    }
    throw new Error(`Signing failed: ${error.message}`);
  }
}

/**
 * Sign a standard message (like a sign-in nonce).
 * 
 * @param {string} message - The string message to sign
 * @returns {Promise<{signature: string, publicKey: string}>}
 */
export async function signSignInMessage(message) {
  const provider = getCasperWalletProvider();
  
  if (!provider) {
    throw new Error('Casper Wallet is not installed');
  }
  
  try {
    const publicKey = await provider.getActivePublicKey();
    const signResult = await provider.signMessage(message, publicKey);
    
    if (!signResult?.signature) {
      throw new Error('Signing failed: no signature returned');
    }
    
    // Convert Uint8Array or whatever object to hex if needed,
    // actually signResult.signature in casper is usually a Uint8Array, we need hex!
    const sigBytes = signResult.signature;
    const sigHex = sigBytes instanceof Uint8Array 
      ? Array.from(sigBytes).map(b => b.toString(16).padStart(2, '0')).join('')
      : (typeof sigBytes === 'string' ? sigBytes : 
         Array.from(new Uint8Array(Object.values(sigBytes))).map(b => b.toString(16).padStart(2, '0')).join(''));
         
    return {
      signature: sigHex,
      publicKey
    };
  } catch (error) {
    throw new Error(`Message signing failed: ${error.message}`);
  }
}

// ── Event Listeners ───────────────────────────────────────────────────────────

/**
 * Listen for wallet events (account changed, disconnected, etc.)
 * 
 * @param {Function} onConnect - Called when wallet connects: (account) => void
 * @param {Function} onDisconnect - Called when wallet disconnects: () => void
 * @param {Function} onAccountChanged - Called when active account changes: (account) => void
 */
export function subscribeToWalletEvents({ onConnect, onDisconnect, onAccountChanged }) {
  if (typeof window === 'undefined') return () => {};
  
  const handleConnect = async (event) => {
    const account = await getActiveAccount();
    onConnect?.(account);
  };
  
  const handleDisconnect = () => {
    onDisconnect?.();
  };
  
  const handleAccountChange = async (event) => {
    const account = await getActiveAccount();
    onAccountChanged?.(account);
  };
  
  window.addEventListener('casper-wallet:connected', handleConnect);
  window.addEventListener('casper-wallet:disconnected', handleDisconnect);
  window.addEventListener('casper-wallet:activeKeyChanged', handleAccountChange);
  
  // Return unsubscribe function
  return () => {
    window.removeEventListener('casper-wallet:connected', handleConnect);
    window.removeEventListener('casper-wallet:disconnected', handleDisconnect);
    window.removeEventListener('casper-wallet:activeKeyChanged', handleAccountChange);
  };
}

// ── Utility: Format Account Hash ──────────────────────────────────────────────

/**
 * Format an account hash for display (truncate middle).
 * @param {string} hash - Full account hash or public key
 * @param {number} chars - Characters to show on each side
 */
export function formatAccountHash(hash, chars = 8) {
  if (!hash) return '';
  return `${hash.slice(0, chars)}...${hash.slice(-chars)}`;
}

/**
 * Creates and signs a native Casper Transfer Deploy for session budget payment.
 * 
 * Uses casper-js-sdk v2 API:
 *  - CLPublicKey.fromHex(hex) — converts "02<66hex>" to CLPublicKey
 *  - DeployUtil.DeployParams — deploy parameters
 *  - DeployUtil.ExecutableDeployItem.newTransfer — builds transfer session
 *  - DeployUtil.makeDeploy(deployParams, payment, session) — assembles deploy
 *  - DeployUtil.deployToJson(deploy) — serializes to JSON
 * 
 * @param {string} amountMotes - Amount in motes (string), e.g. "1000000000" = 1 CSPR
 * @param {string} recipientPublicKeyHex - Platform public key hex (e.g. "02024370ec...")
 * @param {string} networkName - Casper chain name (e.g. "casper-test")
 * @returns {Promise<Object>} Signed deploy as JSON
 */
export async function signCasperTransferDeploy(amountMotes, recipientPublicKeyHex, networkName = 'casper-test') {
  const provider = getCasperWalletProvider();
  if (!provider) {
    throw new Error('Casper Wallet is not installed. Please install it from https://casperwallet.io');
  }

  // --- Step 1: Get sender public key ---
  let activePublicKeyStr;
  try {
    activePublicKeyStr = await provider.getActivePublicKey();
  } catch (err) {
    throw new Error('Wallet is locked or not connected. Please unlock your Casper Wallet and try again.');
  }
  if (!activePublicKeyStr) {
    throw new Error('No active account in Casper Wallet. Please connect your wallet first.');
  }

  // --- Step 2: Build CLPublicKey objects ---
  // casper-js-sdk v2: CLPublicKey.fromHex accepts "01<64hex>" (Ed25519) or "02<66hex>" (Secp256k1)
  const senderCLPubKey = CLPublicKey.fromHex(activePublicKeyStr);

  // recipient must also be a CLPublicKey in v2 (not raw account-hash bytes)
  // The backend must send payTo as the platform's PUBLIC KEY hex, not account hash
  const recipientCLPubKey = CLPublicKey.fromHex(recipientPublicKeyHex);

  // --- Step 3: Build the Deploy ---
  // v2 DeployParams: (publicKey, chainName, gasPrice=1, ttl=1800000ms)
  const deployParams = new DeployUtil.DeployParams(
    senderCLPubKey,
    networkName,
    1,          // gasPrice
    1800000     // ttl: 30 minutes in ms
  );

  // Payment: 1 CSPR gas fee (1,000,000,000 motes) to ensure quick execution on Condor 2.0
  const payment = DeployUtil.standardPayment(1000000000);

  // Transfer session: amount, target (CLPublicKey), source purse (null = main), transfer-id
  const session = DeployUtil.ExecutableDeployItem.newTransfer(
    amountMotes,
    recipientCLPubKey,
    null, // source purse (null = main purse)
    1     // transfer id
  );

  // v2 makeDeploy order: (deployParams, session, payment)
  const deploy = DeployUtil.makeDeploy(deployParams, session, payment);
  const deployJson = DeployUtil.deployToJson(deploy);

  // --- Step 4: Ask Casper Wallet to sign the deploy ---
  let signResult;
  try {
    signResult = await provider.sign(JSON.stringify(deployJson), activePublicKeyStr);
  } catch (err) {
    throw new Error(`Wallet signing failed: ${err.message}`);
  }

  if (signResult?.cancelled) {
    throw new Error('You rejected the payment transaction. Please try again.');
  }
  if (!signResult?.signature) {
    throw new Error('No signature returned from Casper Wallet. Please try again.');
  }

  // --- Step 5: Apply the signature and serialize ---
  // The Casper Wallet signResult.signature is a hex string that ALREADY includes the 
  // '01' (Ed25519) or '02' (Secp256k1) prefix (making it 130 chars).
  // However, DeployUtil.setSignature expects the RAW 64-byte signature array (no prefix),
  // because it adds the prefix itself based on the senderCLPubKey type.
  let rawSignatureBytes;
  if (typeof signResult.signature === 'string') {
    let hexSig = signResult.signature;
    console.log("Wallet returned string signature:", hexSig);
    // Strip the '01' or '02' prefix if it exists and is the full 130 chars
    if ((hexSig.startsWith('01') || hexSig.startsWith('02')) && hexSig.length === 130) {
      hexSig = hexSig.slice(2);
    }
    // Convert hex string to Uint8Array
    rawSignatureBytes = new Uint8Array(hexSig.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
  } else {
    console.log("Wallet returned non-string signature:", signResult.signature);
    // If it's already a Uint8Array (some wallet versions/SDKs might return this)
    // Convert to Uint8Array just in case it's a plain object {0: 2, 1: 171, ...}
    rawSignatureBytes = new Uint8Array(Object.values(signResult.signature));
  }
  console.log("Raw signature bytes length:", rawSignatureBytes.length);

  const signedDeploy = DeployUtil.setSignature(deploy, rawSignatureBytes, senderCLPubKey);
  const finalJson = DeployUtil.deployToJson(signedDeploy);
  console.log("Final signed deploy JSON:", JSON.stringify(finalJson, null, 2));
  return finalJson;
}

