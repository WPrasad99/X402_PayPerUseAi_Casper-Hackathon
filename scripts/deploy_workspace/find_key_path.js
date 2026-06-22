const bip39 = require('bip39');
const { HDKey } = require('@scure/bip32');
const sdk = require('casper-js-sdk');

async function deriveKey() {
  const MNEMONIC = 'simple often chat cover dirt into hazard symbol team urban box spider modify endless rich focus annual stereo pepper poet kiss insane poet link';
  const TARGET_PK = '024370ec2c6c0c22de28e738b1bd55cadb21c9046c9250253c94bf8919302cc8ef';

  const seed = await bip39.mnemonicToSeed(MNEMONIC);

  const paths = [
    "m/44'/506'/0'/0/0",
    "m/44'/506'/0'/0/1",
    "m/44'/506'/0'/0/2",
    "m/44'/60'/0'/0/0",
    "m/44'/148'/0'/0/0",
    "m/44'/506'/0'",
    "m/0'/0'/0'",
  ];

  const hdKey = HDKey.fromMasterSeed(seed);

  for (const path of paths) {
    try {
      const child = hdKey.derive(path);
      if (child.privateKey) {
        const privHex = Buffer.from(child.privateKey).toString('hex');
        const pk = sdk.PrivateKey.fromHex(privHex, sdk.KeyAlgorithm.SECP256K1);
        const pubHex = pk.publicKey.toHex();
        const match = pubHex.toLowerCase() === ('02' + TARGET_PK).toLowerCase() || pubHex.toLowerCase() === TARGET_PK.toLowerCase();
        console.log(path + ': ' + pubHex.slice(0, 20) + '...' + (match ? ' *** MATCH! ***' : ''));
      }
    } catch (e) {
      console.log(path + ': error - ' + e.message.slice(0, 40));
    }
  }
}
deriveKey().catch(e => console.error(e.message));
