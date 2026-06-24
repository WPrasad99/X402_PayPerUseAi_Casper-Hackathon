const fs = require('fs');
const code = fs.readFileSync('node_modules/casper-cep18-js-client/dist/wasm/cep18.js', 'utf8');
const match = code.match(/"([A-Za-z0-9+/=]{1000,})"/);
if (match) {
  fs.writeFileSync('cep18_from_npm.wasm', Buffer.from(match[1], 'base64'));
  console.log('WASM extracted!', match[1].length);
} else {
  console.log('not found');
}
