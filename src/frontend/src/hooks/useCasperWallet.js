/**
 * useCasperWallet React Hook
 * Manages Casper Wallet connection state throughout the app.
 * 
 * Usage:
 *   const { wallet, connect, disconnect, isInstalled } = useCasperWallet();
 */

import { useState, useEffect, useCallback } from 'react';
import {
  isCasperWalletInstalled,
  connectCasperWallet,
  disconnectCasperWallet,
  getActiveAccount,
  subscribeToWalletEvents,
  formatAccountHash,
} from '../api/casperWallet';
import { onPaymentStatus } from '../api/x402Client';

const STORAGE_KEY = 'casper_wallet_connected';

export function useCasperWallet() {
  const [wallet, setWallet] = useState({
    publicKey: null,
    accountHash: null,
    isConnected: false,
    isInstalled: false,
  });
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState(null);
  
  // Payment status tracking
  const [paymentStatus, setPaymentStatus] = useState(null);
  // { type: 'signing'|'settling'|'success'|'failed', amount?, tx?, error? }

  // ── Initialize ──────────────────────────────────────────────
  useEffect(() => {
    const installed = isCasperWalletInstalled();
    
    // Check if previously connected
    const wasConnected = localStorage.getItem(STORAGE_KEY) === 'true';
    
    if (installed && wasConnected) {
      // Try to restore connection silently
      getActiveAccount().then((account) => {
        if (account.isConnected) {
          setWallet({ ...account, isInstalled: true });
        } else {
          localStorage.removeItem(STORAGE_KEY);
          setWallet(prev => ({ ...prev, isInstalled: true }));
        }
      });
    } else {
      setWallet(prev => ({ ...prev, isInstalled: installed }));
    }
    
    // Subscribe to wallet events
    const unsubscribe = subscribeToWalletEvents({
      onConnect: (account) => {
        setWallet({ ...account, isInstalled: true });
        localStorage.setItem(STORAGE_KEY, 'true');
      },
      onDisconnect: () => {
        setWallet({ publicKey: null, accountHash: null, isConnected: false, isInstalled: true });
        localStorage.removeItem(STORAGE_KEY);
      },
      onAccountChanged: (account) => {
        setWallet({ ...account, isInstalled: true });
      }
    });
    
    // Subscribe to payment status events
    const unsubscribePayment = onPaymentStatus((status) => {
      setPaymentStatus(status);
      // Auto-clear success/failed after 5 seconds
      if (status.type === 'success' || status.type === 'failed') {
        setTimeout(() => setPaymentStatus(null), 5000);
      }
    });
    
    return () => {
      unsubscribe();
      unsubscribePayment();
    };
  }, []);
  
  // ── Connect ─────────────────────────────────────────────────
  const connect = useCallback(async () => {
    if (!isCasperWalletInstalled()) {
      setError('Casper Wallet is not installed. Visit https://casperwallet.io to install it.');
      return false;
    }
    
    setIsConnecting(true);
    setError(null);
    
    try {
      const account = await connectCasperWallet();
      setWallet({ ...account, isInstalled: true });
      localStorage.setItem(STORAGE_KEY, 'true');
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally {
      setIsConnecting(false);
    }
  }, []);
  
  // ── Disconnect ───────────────────────────────────────────────
  const disconnect = useCallback(async () => {
    await disconnectCasperWallet();
    setWallet({ publicKey: null, accountHash: null, isConnected: false, isInstalled: isCasperWalletInstalled() });
    localStorage.removeItem(STORAGE_KEY);
    setPaymentStatus(null);
  }, []);
  
  return {
    wallet,
    isConnecting,
    error,
    paymentStatus,
    connect,
    disconnect,
    isInstalled: wallet.isInstalled,
    isConnected: wallet.isConnected,
    publicKey: wallet.publicKey,
    accountHash: wallet.accountHash,
    shortAddress: wallet.publicKey ? formatAccountHash(wallet.publicKey) : null,
    clearError: () => setError(null),
  };
}
