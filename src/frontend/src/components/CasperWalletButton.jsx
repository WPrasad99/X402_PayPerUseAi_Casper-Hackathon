/**
 * CasperWalletButton Component
 * Beautiful connect/disconnect button for Casper Wallet.
 * Shows install prompt if wallet is not installed.
 * Shows account info when connected.
 */

import React, { useState } from 'react';
import { useCasperWallet } from '../hooks/useCasperWallet';

const CASPER_WALLET_URL = 'https://casperwallet.io';

export default function CasperWalletButton({ className = '', compact = false }) {
  const {
    wallet, isConnecting, error, connect, disconnect,
    isInstalled, isConnected, shortAddress, clearError
  } = useCasperWallet();
  const [showDropdown, setShowDropdown] = useState(false);

  // ── Not installed ─────────────────────────────────────────────
  if (!isInstalled) {
    return (
      <a
        href={CASPER_WALLET_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={`casper-install-btn ${className}`}
        style={styles.installBtn}
      >
        <CasperIcon />
        <span>Install Casper Wallet</span>
        <ExternalIcon />
      </a>
    );
  }

  // ── Connected ─────────────────────────────────────────────────
  if (isConnected) {
    return (
      <div style={styles.connectedWrapper} className={className}>
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          style={styles.connectedBtn}
          className="casper-connected-btn"
        >
          <div style={styles.statusDot} />
          <CasperIcon size={16} />
          {!compact && (
            <span style={styles.address}>{shortAddress}</span>
          )}
          <ChevronIcon />
        </button>

        {showDropdown && (
          <>
            <div
              style={styles.backdrop}
              onClick={() => setShowDropdown(false)}
            />
            <div style={styles.dropdown}>
              <div style={styles.dropdownHeader}>
                <div style={styles.networkBadge}>
                  <span style={styles.networkDot} />
                  Casper Testnet
                </div>
                <p style={styles.fullAddress}>{wallet.publicKey}</p>
              </div>
              
              <a
                href={`https://testnet.cspr.live/account/${wallet.publicKey}`}
                target="_blank"
                rel="noopener noreferrer"
                style={styles.dropdownItem}
              >
                <ExternalIcon size={14} />
                View on Explorer
              </a>
              
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(wallet.publicKey || '');
                  setShowDropdown(false);
                }}
                style={styles.dropdownItem}
              >
                <CopyIcon size={14} />
                Copy Public Key
              </button>
              
              <div style={styles.dropdownDivider} />
              
              <button
                onClick={() => { disconnect(); setShowDropdown(false); }}
                style={{ ...styles.dropdownItem, color: '#ff4d4d' }}
              >
                <DisconnectIcon size={14} />
                Disconnect
              </button>
            </div>
          </>
        )}
      </div>
    );
  }

  // ── Not connected ─────────────────────────────────────────────
  return (
    <div className={className}>
      {error && (
        <div style={styles.errorToast} onClick={clearError}>
          ⚠️ {error}
          <span style={{ marginLeft: 8, cursor: 'pointer' }}>✕</span>
        </div>
      )}
      <button
        onClick={connect}
        disabled={isConnecting}
        style={styles.connectBtn}
        className="casper-connect-btn"
      >
        {isConnecting ? (
          <>
            <Spinner />
            <span>Connecting...</span>
          </>
        ) : (
          <>
            <CasperIcon />
            <span>Connect Casper Wallet</span>
          </>
        )}
      </button>
    </div>
  );
}

// ── Payment Status Toast ──────────────────────────────────────────────────────
export function PaymentStatusToast() {
  const { paymentStatus } = useCasperWallet();
  
  if (!paymentStatus) return null;
  
  const config = {
    signing: { bg: '#1a1a3e', border: '#6366f1', icon: '✍️', text: 'Sign payment in Casper Wallet...' },
    settling: { bg: '#0f2922', border: '#10b981', icon: '⛓️', text: `Settling on Casper Testnet...` },
    success: { bg: '#0f2922', border: '#10b981', icon: '✅', text: `Payment settled! ${paymentStatus.amount || ''}` },
    failed: { bg: '#2d0a0a', border: '#ef4444', icon: '❌', text: `Payment failed: ${paymentStatus.error || 'Unknown error'}` },
  };
  
  const c = config[paymentStatus.type] || config.failed;
  
  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      background: c.bg, border: `1px solid ${c.border}`,
      borderRadius: 12, padding: '12px 20px',
      display: 'flex', alignItems: 'center', gap: 12,
      color: '#fff', fontSize: 14, fontWeight: 500,
      boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
      maxWidth: 380,
      animation: 'slideUp 0.3s ease',
    }}>
      <span style={{ fontSize: 20 }}>{c.icon}</span>
      <div>
        <div>{c.text}</div>
        {paymentStatus.tx && (
          <a
            href={`https://testnet.cspr.live/deploy/${paymentStatus.tx}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: '#10b981', fontSize: 12, textDecoration: 'none' }}
          >
            View transaction ↗
          </a>
        )}
      </div>
      {paymentStatus.type === 'settling' && <Spinner size={16} />}
    </div>
  );
}

// ── Icon Components ───────────────────────────────────────────────────────────

function CasperIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="16" fill="#FF0012" opacity="0.15" />
      <path
        d="M16 6C10.477 6 6 10.477 6 16s4.477 10 10 10 10-4.477 10-10S21.523 6 16 6zm0 18c-4.418 0-8-3.582-8-8s3.582-8 8-8 8 3.582 8 8-3.582 8-8 8z"
        fill="#FF0012"
      />
      <circle cx="16" cy="16" r="4" fill="#FF0012" />
    </svg>
  );
}

function ExternalIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function CopyIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
    </svg>
  );
}

function DisconnectIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
    </svg>
  );
}

function Spinner({ size = 18 }) {
  return (
    <div style={{
      width: size, height: size,
      border: '2px solid rgba(255,255,255,0.3)',
      borderTopColor: '#fff',
      borderRadius: '50%',
      animation: 'spin 0.8s linear infinite',
      flexShrink: 0,
    }} />
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = {
  installBtn: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: 'linear-gradient(135deg, #1a1a2e, #16213e)',
    border: '1px solid rgba(255,255,255,0.15)',
    color: '#fff', borderRadius: 10, padding: '10px 18px',
    fontSize: 14, fontWeight: 600, cursor: 'pointer',
    textDecoration: 'none', transition: 'all 0.2s',
  },
  connectBtn: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: 'linear-gradient(135deg, #FF0012, #cc000f)',
    border: 'none', color: '#fff', borderRadius: 10,
    padding: '10px 20px', fontSize: 14, fontWeight: 700,
    cursor: 'pointer', transition: 'all 0.2s',
  },
  connectedWrapper: { position: 'relative' },
  connectedBtn: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: 'rgba(255, 0, 18, 0.1)', border: '1px solid rgba(255,0,18,0.3)',
    color: '#fff', borderRadius: 10, padding: '8px 16px',
    fontSize: 14, fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
  },
  statusDot: {
    width: 8, height: 8, borderRadius: '50%',
    background: '#10b981', boxShadow: '0 0 6px #10b981',
    flexShrink: 0,
  },
  address: { fontFamily: 'monospace', fontSize: 13 },
  backdrop: {
    position: 'fixed', inset: 0, zIndex: 50,
  },
  dropdown: {
    position: 'absolute', top: 'calc(100% + 8px)', right: 0,
    background: '#0d1117', border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: 12, minWidth: 260, zIndex: 100,
    overflow: 'hidden', boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
  },
  dropdownHeader: {
    padding: '16px', borderBottom: '1px solid rgba(255,255,255,0.08)',
  },
  networkBadge: {
    display: 'flex', alignItems: 'center', gap: 6,
    fontSize: 12, color: '#10b981', marginBottom: 8, fontWeight: 600,
  },
  networkDot: {
    width: 6, height: 6, borderRadius: '50%',
    background: '#10b981', boxShadow: '0 0 4px #10b981',
  },
  fullAddress: {
    fontFamily: 'monospace', fontSize: 11,
    color: 'rgba(255,255,255,0.5)', wordBreak: 'break-all', margin: 0,
  },
  dropdownItem: {
    display: 'flex', alignItems: 'center', gap: 10,
    width: '100%', padding: '12px 16px',
    background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.8)',
    fontSize: 14, cursor: 'pointer', textDecoration: 'none',
    transition: 'background 0.15s',
  },
  dropdownDivider: {
    borderTop: '1px solid rgba(255,255,255,0.08)', margin: '4px 0',
  },
  errorToast: {
    background: '#2d0a0a', border: '1px solid #ef4444',
    color: '#fca5a5', borderRadius: 8, padding: '8px 12px',
    fontSize: 13, marginBottom: 8, cursor: 'pointer',
    display: 'flex', alignItems: 'center',
  },
};
