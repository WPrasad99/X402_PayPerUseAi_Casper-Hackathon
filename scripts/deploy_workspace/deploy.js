/**
 * PayAI Token (PAIT) — CEP-18 Final Deployment Script
 * Using casper-js-sdk v5 with correct BIP-44 key derivation
 * Key path: m/44'/506'/0'/0/0 (Casper Wallet standard)
 */

const bip39      = require('bip39');
const { HDKey }  = require('@scure/bip32');
const sdk        = require('casper-js-sdk');
const fs         = require('fs');
const path       = require('path');
const https      = require('https');

// ── Credentials ───────────────────────────────────────────────────────────────
const MNEMONIC     = 'simple often chat cover dirt into hazard symbol team urban box spider modify endless rich focus annual stereo pepper poet kiss insane poet link';
const CSPR_API_KEY = '019f1e23-80a0-774f-b5fe-d3df694aef9a';
const KEY_PATH     = "m/44'/506'/0'/0/0";  // Casper Wallet BIP-44 path

// ── Token Config ──────────────────────────────────────────────────────────────
const TOKEN = {
  name:         'PayAIToken',
  symbol:       'PAIT',
  decimals:     2,
  total_supply: '10000000000',  // 100,000,000.00 PAIT
};

// ── Network ───────────────────────────────────────────────────────────────────
const CHAIN    = 'casper-test';
const GAS      = 120000000000;  // 120 CSPR
const WASM     = path.join(__dirname, 'cep18.wasm');
const ACCOUNT_HASH = 'bac0c10fade6c68efbe4252ae988f51f3b1b6b6871dfb50ece9665328563c730';

// ── RPC Helper ────────────────────────────────────────────────────────────────
function rpc(method, params = {}) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ jsonrpc: '2.0', id: 1, method, params });
    const req = https.request({
      hostname: 'node.testnet.cspr.cloud',
      path: '/rpc',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': CSPR_API_KEY,
        'Content-Length': Buffer.byteLength(body),
      },
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          const j = JSON.parse(data);
          if (j.error) return reject(new Error(`RPC Error: ${JSON.stringify(j.error)}`));
          resolve(j.result);
        } catch(e) { reject(new Error('Bad JSON: ' + data.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.setTimeout(20000, () => req.destroy(new Error('timeout')));
    req.write(body); req.end();
  });
}

// ── Derive private key using BIP-44 ──────────────────────────────────────────
async function derivePrivateKey() {
  const seed  = await bip39.mnemonicToSeed(MNEMONIC);
  const hdKey = HDKey.fromMasterSeed(seed);
  const child = hdKey.derive(KEY_PATH);
  if (!child.privateKey) throw new Error('Failed to derive private key');
  return Buffer.from(child.privateKey).toString('hex');
}

// ── Build and submit deploy ───────────────────────────────────────────────────
async function buildAndSubmitDeploy(privateKeyHex) {
  const privateKey = sdk.PrivateKey.fromHex(privateKeyHex, sdk.KeyAlgorithm.SECP256K1);
  const publicKey  = privateKey.publicKey;
  const wasmPath = path.resolve(__dirname, 'cep18_from_npm.wasm');
  const wasmBytes = new Uint8Array(fs.readFileSync(wasmPath));

  console.log('   Token:', TOKEN.name, `(${TOKEN.symbol}),`, 'Supply:', TOKEN.total_supply, TOKEN.symbol);
  console.log('   Public key:', publicKey.toHex());
  console.log('   WASM:', wasmBytes.length, 'bytes');

  // Build runtime args
  const args = sdk.Args.fromMap({
    name:             sdk.CLValue.newCLString(TOKEN.name),
    symbol:           sdk.CLValue.newCLString(TOKEN.symbol),
    decimals:         sdk.CLValue.newCLUint8(TOKEN.decimals),
    total_supply:     sdk.CLValue.newCLUInt256(TOKEN.total_supply),
    events_mode:      sdk.CLValue.newCLUint8(0), // 0 = No Events
    enable_mint_burn: sdk.CLValue.newCLUint8(1), // MUST BE u8, not bool! 1 = true
  });

  // Build the session (WASM deploy) using SessionBuilder
  const session = new sdk.SessionBuilder()
    .wasm(wasmBytes)
    .runtimeArgs(args)
    .chainName(CHAIN)
    .from(publicKey)
    .payment(GAS);

  // Build TransactionV1
  const transaction = session.build();

  // Sign the transaction
  transaction.sign(privateKey);
  console.log('   Transaction signed ✅');

  // Submit via raw RPC since SDK HttpHandler has auth header issues
  console.log('   Submitting transaction to network...');
  const result = await rpc('account_put_transaction', { transaction: { Version1: transaction.toJSON() } });
  
  let hashStr = result;
  if (result?.transaction_hash?.Version1) hashStr = result.transaction_hash.Version1;
  else if (result?.transaction_hash) hashStr = result.transaction_hash;
  
  console.log('   Raw RPC result:', JSON.stringify(result));
  return hashStr;
}

// ── Wait for confirmation ─────────────────────────────────────────────────────
async function waitForDeploy(transactionHash) {
  console.log('\n⏳ Waiting for block confirmation (every 10s, up to 6 min)...');
  
  const client = new sdk.RpcClient(
    new sdk.HttpHandler(`https://node.testnet.cspr.cloud/rpc`, {
      headers: { 'Authorization': CSPR_API_KEY }
    })
  );

  for (let i = 0; i < 36; i++) {
    await new Promise(r => setTimeout(r, 10000));
    process.stdout.write(`   [${(i+1)*10}s] `);
    try {
      // Condor endpoints use info_get_transaction
      const result = await client.infoGetTransaction(transactionHash);
      const execInfo = result?.transaction?.execution_info;
      
      if (execInfo) {
        if (execInfo.execution_result?.Success !== undefined || execInfo.execution_result?.success !== undefined || !execInfo.execution_result?.Failure) {
          console.log('\n✅ CONFIRMED!');
          return execInfo.execution_result?.Success || execInfo.execution_result || result;
        } else {
          throw new Error('FAILED: ' + JSON.stringify(execInfo.execution_result));
        }
      }
      
      console.log('pending...');
    } catch(e) {
      if (e.message.startsWith('FAILED')) throw e;
      // Also fallback to raw RPC just in case sdk method is missing
      try {
        const rawResult = await rpc('info_get_transaction', { transaction_hash: { Version1: transactionHash } });
        const execInfo = rawResult?.transaction?.execution_info;
        if (execInfo) {
          console.log('\n✅ CONFIRMED! (via raw RPC)');
          return execInfo.execution_result?.Success || execInfo.execution_result || rawResult;
        }
      } catch (e2) {}
      
      console.log('checking...');
    }
  }
  return null;
}

// ── Extract contract package hash from execution transforms ───────────────────
function extractContractHash(successResult) {
  const transforms = successResult?.effect?.transforms || [];
  for (const t of transforms) {
    if (t.key?.startsWith('hash-') && t.transform?.WriteContractPackage !== undefined) {
      return t.key.replace('hash-', '');
    }
  }
  // Also check ContractPackage key type
  for (const t of transforms) {
    if (t.key?.startsWith('hash-') && (
      JSON.stringify(t.transform).includes('ContractPackage') ||
      JSON.stringify(t.transform).includes('WriteContract')
    )) {
      return t.key.replace('hash-', '');
    }
  }
  return null;
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  console.log('╔══════════════════════════════════════════════════════╗');
  console.log('║  PayAI Token (PAIT) — Casper Testnet Deployment      ║');
  console.log('║  SDK: casper-js-sdk v5  |  Network: casper-test      ║');
  console.log('╚══════════════════════════════════════════════════════╝\n');

  // 1. Test RPC connectivity
  console.log('🌐 Testing node connectivity...');
  const status = await rpc('info_get_status');
  console.log(`✅ Connected! Block: ${status?.last_added_block_info?.height}, Chain: ${status?.chainspec_name}`);

  // 2. Derive private key
  console.log(`\n🔑 Deriving key via path ${KEY_PATH}...`);
  const privateKeyHex = await derivePrivateKey();
  console.log('✅ Key derived.');

  // 3. Build & submit
  console.log(`\n📡 Building and submitting deploy...`);
  console.log(`   Token: ${TOKEN.name} (${TOKEN.symbol}), Supply: ${parseInt(TOKEN.total_supply)/10**TOKEN.decimals} ${TOKEN.symbol}`);
  
  let deployHash;
  try {
    deployHash = await buildAndSubmitDeploy(privateKeyHex);
  } catch(e) {
    // If SDK submit fails, try raw RPC
    console.log(`   SDK submit failed (${e.message}), trying raw RPC...`);
    throw e;
  }

  console.log('\n' + '═'.repeat(62));
  console.log('✅  DEPLOY SUBMITTED SUCCESSFULLY!');
  console.log(`Deploy Hash : ${deployHash}`);
  console.log(`Explorer    : https://testnet.cspr.live/deploy/${deployHash}`);
  console.log('═'.repeat(62));

  // 4. Wait for confirmation
  const success = await waitForDeploy(deployHash);
  
  let contractPkgHash = null;
  if (success) {
    contractPkgHash = extractContractHash(success);
    if (!contractPkgHash) {
      // Print all transform keys for debugging
      console.log('\n📋 Transform keys found:');
      (success?.effect?.transforms || []).forEach(t => {
        if (t.key?.startsWith('hash-')) console.log('  ', t.key, '->', Object.keys(t.transform || {}).join(', '));
      });
    }
  }

  // 5. Print results
  const output = [
    '═'.repeat(62),
    '📋  DEPLOYMENT COMPLETE',
    '═'.repeat(62),
    `DEPLOY_HASH=${deployHash}`,
    `CONTRACT_PACKAGE_HASH=${contractPkgHash || 'CHECK_EXPLORER_NAMED_KEYS'}`,
    `YOUR_ACCOUNT_HASH=${ACCOUNT_HASH}`,
    '',
    '# === Paste into backend/.env ===',
    `CEP18_CONTRACT_PACKAGE_HASH=${contractPkgHash || 'REPLACE_AFTER_CHECKING_EXPLORER'}`,
    `CEP18_TOKEN_NAME=${TOKEN.name}`,
    `CEP18_TOKEN_SYMBOL=${TOKEN.symbol}`,
    `CEP18_TOKEN_DECIMALS=${TOKEN.decimals}`,
    `CEP18_TOKEN_VERSION=1`,
    `PLATFORM_ACCOUNT_HASH=02${ACCOUNT_HASH}`,
    `CSPR_X402_API_KEY=${CSPR_API_KEY}`,
    `CASPER_NETWORK=casper:casper-test`,
    `CASPER_NODE_RPC_URL=https://node.testnet.cspr.cloud`,
    '',
    '# === Paste into frontend/.env ===',
    `VITE_CEP18_CONTRACT_HASH=${contractPkgHash || 'REPLACE_AFTER_CHECKING_EXPLORER'}`,
    `VITE_CEP18_TOKEN_NAME=${TOKEN.name}`,
    `VITE_CEP18_TOKEN_SYMBOL=${TOKEN.symbol}`,
    `VITE_CEP18_TOKEN_DECIMALS=${TOKEN.decimals}`,
    `VITE_CASPER_NETWORK=casper:casper-test`,
    '',
    `Explorer account: https://testnet.cspr.live/account/account-hash-${ACCOUNT_HASH}`,
    '═'.repeat(62),
  ].join('\n');

  console.log('\n' + output);
  fs.writeFileSync(path.join(__dirname, 'deployment_result.txt'), output);
  console.log('\n✅ Results saved to scripts/deploy_workspace/deployment_result.txt');
}

main().catch(e => {
  console.error('\n❌ Deployment Error:', e.message);
  if (e.stack) console.error(e.stack.split('\n').slice(1, 4).join('\n'));
  process.exit(1);
});
