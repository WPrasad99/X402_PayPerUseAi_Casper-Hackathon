/**
 * x402 Payment Client — Session Mode
 * 
 * Handles the "pay once per session" flow:
 *  1. First chat request → gets 402 from backend
 *  2. Shows wallet popup ONCE asking user to approve a session budget (default 1 CSPR)
 *  3. Signs TransferAuthorization → backend settles on-chain → returns session token
 *  4. Session token stored in memory → sent as X-Session-Token on all subsequent requests
 *  5. No wallet popup for subsequent messages — balance just decreases silently
 *  6. When session expires or balance runs low → ask for new session
 * 
 * Also supports per-request fallback (PAYMENT-SIGNATURE) for single-shot requests.
 */

import {
  getCasperWalletProvider,
  getActiveAccount,
  signX402Authorization,
  signCasperTransferDeploy
} from './casperWallet';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '';

// ── Configuration ─────────────────────────────────────────────────────────────
const PAYMENT_CONFIG = {
  tokenName: import.meta.env.VITE_CEP18_TOKEN_NAME || 'CSPR',
  tokenVersion: import.meta.env.VITE_CEP18_TOKEN_VERSION || '1',
  contractHash: import.meta.env.VITE_CEP18_CONTRACT_HASH || '',
  network: import.meta.env.VITE_CASPER_NETWORK || 'casper:casper-test',
  maxTimeoutSeconds: parseInt(import.meta.env.VITE_MAX_TIMEOUT_SECONDS || '300'),
  // Default session budget: 1 CSPR = 1,000,000,000 motes
  // Minimum native transfer amount on Casper is 2.5 CSPR (2,500,000,000 motes). 
  // Any amount lower than this will result in an 'Invalid Deploy' error from the network.
  defaultSessionBudgetUnits: parseInt(import.meta.env.VITE_SESSION_BUDGET_UNITS || '2500000000'),
};

// ── In-Memory Session State ───────────────────────────────────────────────────
let _currentSession = null;
// {
//   token: string,
//   remaining_units: number,
//   remaining_cspr: number,
//   tx_hash: string,
//   created_at: number,   // Date.now()
//   expires_at: number,   // Date.now() + 7200000
// }

/** Get current session or null */
export function getSession() {
  if (!_currentSession) return null;
  if (Date.now() > _currentSession.expires_at) {
    _currentSession = null;
    return null;
  }
  return _currentSession;
}

/** Update session remaining balance from response headers */
export function syncSessionFromHeaders(headers) {
  if (!_currentSession) return;
  const remaining = headers.get('X-Session-Remaining');
  if (remaining !== null) {
    _currentSession.remaining_units = parseInt(remaining);
    _currentSession.remaining_cspr = _currentSession.remaining_units / 1e9;
    emitPaymentStatus({
      type: 'balance_update',
      remaining_cspr: _currentSession.remaining_cspr,
      remaining_units: _currentSession.remaining_units,
      session_token: _currentSession.token,
    });
  }
}

/** Clear the current session (e.g. on logout) */
export function clearSession() {
  _currentSession = null;
}

// ── Payment Status Listeners ──────────────────────────────────────────────────
let _paymentStatusListeners = [];

export function onPaymentStatus(listener) {
  _paymentStatusListeners.push(listener);
  return () => {
    _paymentStatusListeners = _paymentStatusListeners.filter(l => l !== listener);
  };
}

function emitPaymentStatus(status) {
  _paymentStatusListeners.forEach(l => l(status));
}

// ── Crypto Helpers ────────────────────────────────────────────────────────────

function generateNonce() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

function generateValidityWindow(timeoutSeconds = 300) {
  const now = Math.floor(Date.now() / 1000);
  return [String(now - 5), String(now + timeoutSeconds)];
}

// ── Account Hash ──────────────────────────────────────────────────────────────

async function getPayerAccountHash(publicKey) {
  try {
    const resp = await fetch(`${BASE_URL}/api/v1/wallet/account-hash/${publicKey}`);
    if (resp.ok) {
      const data = await resp.json();
      return data.accountHash;
    }
  } catch (e) {
    console.warn('Could not fetch account hash:', e);
  }
  return publicKey;
}

// ── Build PAYMENT-SIGNATURE Header ───────────────────────────────────────────

function buildPaymentSignatureHeader(
  paymentRequirements,
  resourceUrl,
  payerPublicKey,
  payerAccountHash,
  signature,
  authorization
) {
  const payload = {
    x402Version: 2,
    resource: {
      url: resourceUrl,
      description: 'PayPerUseAI Session Budget',
      mimeType: 'application/json'
    },
    accepted: {
      scheme: 'exact',
      network: paymentRequirements.network,
      asset: paymentRequirements.asset,
      amount: paymentRequirements.amount,
      payTo: paymentRequirements.payTo,
      maxTimeoutSeconds: paymentRequirements.maxTimeoutSeconds,
      extra: paymentRequirements.extra
    },
    payload: {
      signature,
      publicKey: payerPublicKey,
      authorization
    }
  };
  return btoa(JSON.stringify(payload));
}

// ── Core: Create a Payment Session ───────────────────────────────────────────

/**
 * Creates a new payment session by:
 *  1. Getting payment requirements from a 402 response
 *  2. Asking the user to sign a session budget authorization
 *  3. Posting to /api/v1/payment/session/create
 *  4. Storing the session token in memory
 * 
 * @param {Object} paymentData - The parsed 402 response body
 * @param {Object} x402Options - Callbacks: onPaymentRequired, onPaymentSigning, onPaymentSuccess
 * @returns {string} The session token
 */
async function createPaymentSession(paymentData, x402Options = {}) {
  const accepts = paymentData.accepts || [];
  if (accepts.length === 0) throw new Error('No payment options in 402 response');

  const paymentRequirements = accepts[0];
  
  // Use the session budget (1 CSPR by default) rather than the per-request cost
  const sessionBudgetUnits = PAYMENT_CONFIG.defaultSessionBudgetUnits;
  const displayAmount = `${(sessionBudgetUnits / 1e9).toFixed(4)} CSPR`;

  emitPaymentStatus({ type: 'session_required', amount: displayAmount, budget_units: sessionBudgetUnits });
  x402Options.onPaymentRequired?.({ amount: sessionBudgetUnits, displayAmount, isSession: true });

  // Get the payer's wallet info
  const { publicKey, isConnected } = await getActiveAccount();
  if (!isConnected || !publicKey) {
    throw new Error('Wallet not connected. Please connect your Casper Wallet first.');
  }

  const payerAccountHash = await getPayerAccountHash(publicKey);
  emitPaymentStatus({ type: 'signing', amount: displayAmount });
  x402Options.onPaymentSigning?.({ amount: displayAmount, isSession: true });

  // BRANCH: Native CSPR vs Custom Token (EIP-712)
  const isNativeCasper = paymentRequirements.asset === 'casper';

  let sessionData;

  if (isNativeCasper) {
    // 1) NATIVE CSPR: Sign an on-chain Casper Transfer Deploy
    let deployJson;
    try {
      deployJson = await signCasperTransferDeploy(
        String(sessionBudgetUnits),
        paymentRequirements.payTo,
        paymentRequirements.network.replace('casper:', '') || 'casper-test'
      );
    } catch (error) {
      emitPaymentStatus({ type: 'failed', error: error.message });
      throw error;
    }

    emitPaymentStatus({ type: 'settling', amount: displayAmount });
    x402Options.onPaymentSettling?.(); // Notify UI to show loading spinner

    const authToken = localStorage.getItem('auth_token');
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

    // Send to backend to broadcast and await confirmation (takes ~15 seconds)
    const sessionResp = await fetch(`${BASE_URL}/api/v1/payment/session/create-onchain`, {
      method: 'POST',
      credentials: 'include',
      headers: headers,
      body: JSON.stringify({
        deploy: deployJson,
        budget_units: sessionBudgetUnits,
      }),
    });

    if (!sessionResp.ok) {
      let errMsg = 'On-chain session creation failed';
      try {
        const errBody = await sessionResp.json();
        errMsg = errBody.detail || errBody.error || errMsg;
      } catch (e) { }
      emitPaymentStatus({ type: 'failed', error: errMsg });
      throw new Error(errMsg);
    }

    sessionData = await sessionResp.json();

  } else {
    // 2) CUSTOM TOKEN: Sign EIP-712 Off-Chain Authorization
    const nonce = generateNonce();
    const [validAfter, validBefore] = generateValidityWindow(
      paymentRequirements.maxTimeoutSeconds || 300
    );
  
    const authorization = {
      from: payerAccountHash,
      to: paymentRequirements.payTo,
      value: String(sessionBudgetUnits),
      validAfter,
      validBefore,
      nonce,
    };
  
    let signature, signingPublicKey;
    try {
      const sigResult = await signX402Authorization(authorization, {
        name: paymentRequirements.extra?.name || PAYMENT_CONFIG.tokenName,
        version: paymentRequirements.extra?.version || PAYMENT_CONFIG.tokenVersion,
        contractHash: paymentRequirements.asset || PAYMENT_CONFIG.contractHash,
      });
      signature = sigResult.signature;
      signingPublicKey = sigResult.publicKey;
    } catch (error) {
      emitPaymentStatus({ type: 'failed', error: error.message });
      throw error;
    }
  
    const resourceUrl = `${window.location.origin}/api/v1/chat`;
    const paymentSignatureHeader = buildPaymentSignatureHeader(
      { ...paymentRequirements, amount: String(sessionBudgetUnits) },
      resourceUrl,
      signingPublicKey,
      payerAccountHash,
      signature,
      authorization
    );
  
    emitPaymentStatus({ type: 'settling', amount: displayAmount });
  
    const authToken = localStorage.getItem('auth_token');
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

    const sessionResp = await fetch(`${BASE_URL}/api/v1/payment/session/create`, {
      method: 'POST',
      credentials: 'include',
      headers: headers,
      body: JSON.stringify({
        payment_signature: paymentSignatureHeader,
        budget_units: sessionBudgetUnits,
      }),
    });
  
    if (!sessionResp.ok) {
      let errMsg = 'Session creation failed';
      try {
        const errBody = await sessionResp.json();
        errMsg = errBody.detail || errBody.error || errMsg;
      } catch (e) { }
      emitPaymentStatus({ type: 'failed', error: errMsg });
      throw new Error(errMsg);
    }
  
    sessionData = await sessionResp.json();
  }
  
  // Store session in memory
  _currentSession = {
    token: sessionData.session_token,
    remaining_units: sessionData.remaining_units,
    remaining_cspr: sessionData.remaining_cspr,
    tx_hash: sessionData.tx_hash,
    budget_cspr: sessionData.budget_cspr,
    created_at: Date.now(),
    expires_at: Date.now() + (7200 * 1000), // 2 hours
  };

  x402Options.onPaymentSuccess?.({
    amount: displayAmount,
    txHash: sessionData.tx_hash,
    isSession: true,
    remaining_cspr: sessionData.remaining_cspr,
    session_token: sessionData.session_token,
  });

  emitPaymentStatus({
    type: 'session_created',
    amount: displayAmount,
    tx: sessionData.tx_hash,
    remaining_cspr: sessionData.remaining_cspr,
    session_token: sessionData.session_token,
  });

  return sessionData.session_token;
}

// ── Main x402 Fetch (Session Mode) ───────────────────────────────────────────

/**
 * Drop-in replacement for fetch() with session-based x402 payment.
 * 
 * On first call: triggers wallet popup for session budget approval.
 * On subsequent calls: uses cached session token silently.
 * 
 * @param {string} url - API endpoint
 * @param {RequestInit} options - Standard fetch options
 * @param {Object} x402Options - Callbacks
 */
export async function x402Fetch(url, options = {}, x402Options = {}) {
  const session = getSession();
  
  if (session) {
    // Have an active session — use it directly, no wallet popup
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        'X-Session-Token': session.token,
      }
    });
    
    syncSessionFromHeaders(response.headers);
    
    if (response.status === 402) {
      // Session expired or balance depleted on the server — create new session
      const paymentData = await response.json();
      const reason = paymentData.invalidReason;
      
      if (reason === 'session_expired' || reason === 'session_balance_depleted') {
        _currentSession = null;
        // Recurse to create new session
        return x402Fetch(url, options, x402Options);
      }
      
      throw new Error(paymentData.invalidMessage || 'Payment required');
    }
    
    return response;
  }
  
  // No session — make the initial request to get a 402
  const firstResponse = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    }
  });
  
  if (firstResponse.status !== 402) {
    return firstResponse;
  }
  
  // Got 402 — create a new session (wallet popup happens here)
  const paymentData = await firstResponse.json();
  await createPaymentSession(paymentData, x402Options);
  
  // Retry with the new session token
  const session2 = getSession();
  if (!session2) throw new Error('Session creation failed');
  
  const retryResponse = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
      'X-Session-Token': session2.token,
    }
  });
  
  syncSessionFromHeaders(retryResponse.headers);
  return retryResponse;
}

// ── Streaming x402 Fetch (for SSE/chat streaming) ────────────────────────────

/**
 * Session-aware fetch for streaming responses (SSE chat).
 * Uses the same session token flow as x402Fetch.
 */
export async function x402StreamFetch(url, options = {}, x402Options = {}) {
  const session = getSession();
  
  if (session) {
    // Have active session — stream directly
    const streamResponse = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        'X-Session-Token': session.token,
      }
    });
    
    syncSessionFromHeaders(streamResponse.headers);
    
    if (streamResponse.status === 402) {
      const paymentData = await streamResponse.json();
      const reason = paymentData.invalidReason;
      
      if (reason === 'session_expired' || reason === 'session_balance_depleted') {
        _currentSession = null;
        return x402StreamFetch(url, options, x402Options);
      }
      
      throw new Error(paymentData.invalidMessage || 'Payment required');
    }
    
    return streamResponse;
  }
  
  // No session — do a preflight to get 402 with payment requirements
  const preflightResponse = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
      'X-Preflight': 'true',
    }
  });
  
  if (preflightResponse.status === 402) {
    const paymentData = await preflightResponse.json();
    await createPaymentSession(paymentData, x402Options);
    
    // Now do the real streaming request with session token
    const session2 = getSession();
    if (!session2) throw new Error('Session creation failed');
    
    const streamResponse = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        'X-Session-Token': session2.token,
      }
    });
    
    syncSessionFromHeaders(streamResponse.headers);
    
    if (streamResponse.status === 402) {
      const errBody = await streamResponse.json().catch(() => ({}));
      throw new Error(errBody.invalidMessage || 'Payment rejected after session creation');
    }
    
    return streamResponse;
  }
  
  // Server didn't require payment (shouldn't happen for protected routes)
  return preflightResponse;
}

// ── Helper: Get Payment Config from Backend ───────────────────────────────────

let _cachedPaymentConfig = null;

export async function getPaymentConfig() {
  if (_cachedPaymentConfig) return _cachedPaymentConfig;
  try {
    const resp = await fetch(`${BASE_URL}/api/v1/payment/config`);
    if (resp.ok) {
      _cachedPaymentConfig = await resp.json();
      return _cachedPaymentConfig;
    }
  } catch (e) {
    console.warn('Failed to fetch payment config:', e);
  }
  return null;
}

