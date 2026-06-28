const { Keys, CasperClient, Contracts, RuntimeArgs, CLValueBuilder, DeployUtil } = require('casper-js-sdk');
const bip39 = require('bip39');
const { HDKey } = require('@scure/bip32');
const fs = require('fs');
const path = require('path');
const https = require('https');

const MNEMONIC = 'simple often chat cover dirt into hazard symbol team urban box spider modify endless rich focus annual stereo pepper poet kiss insane poet link';
const CSPR_API_KEY = '019f1e23-80a0-774f-b5fe-d3df694aef9a';
const KEY_PATH = "m/44'/506'/0'/0/0";

const TOKEN = {
  name: 'PayAIToken',
  symbol: 'PAIT',
  decimals: 2,
  total_supply: '10000000000',
};

const CHAIN = 'casper-test';
const GAS = '120000000000'; // 120 CSPR

async function derivePrivateKey() {
  const seed = await bip39.mnemonicToSeed(MNEMONIC);
  const hdKey = HDKey.fromMasterSeed(seed);
  const child = hdKey.derive(KEY_PATH);
  return child.privateKey;
}

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
      res.on('end', () => resolve(JSON.parse(data).result));
    });
    req.on('error', reject);
    req.write(body); req.end();
  });
}

async function main() {
  console.log('Deriving keys...');
  const privateKeyBytes = await derivePrivateKey();
  const keys = Keys.Secp256K1.parsePrivateKey(privateKeyBytes, 'raw');
  const publicKey = keys.publicKey;
  console.log('Public key:', publicKey.toHex());

  const wasmPath = path.resolve(__dirname, 'cep18_from_npm.wasm');
  const wasmBytes = new Uint8Array(fs.readFileSync(wasmPath));

  const args = RuntimeArgs.fromMap({
    name: CLValueBuilder.string(TOKEN.name),
    symbol: CLValueBuilder.string(TOKEN.symbol),
    decimals: CLValueBuilder.u8(TOKEN.decimals),
    total_supply: CLValueBuilder.u256(TOKEN.total_supply),
    events_mode: CLValueBuilder.u8(0),
    enable_mint_burn: CLValueBuilder.u8(1),
  });

  console.log('Building Deploy...');
  let deploy = DeployUtil.makeDeploy(
    new DeployUtil.DeployParams(publicKey, CHAIN, GAS, 1800000),
    DeployUtil.ExecutableDeployItem.newModuleBytes(wasmBytes, args),
    DeployUtil.standardPayment(GAS)
  );

  console.log('Signing Deploy...');
  deploy = DeployUtil.signDeploy(deploy, keys);
  
  console.log('Deploy Hash:', Buffer.from(deploy.hash).toString('hex'));

  console.log('Submitting Deploy (using raw RPC)...');
  const result = await rpc('account_put_deploy', { deploy: DeployUtil.deployToJson(deploy) });
  console.log('Submit Result:', result);
  
  console.log('Deployment submitted! Wait for it to confirm!');
}

main().catch(console.error);
