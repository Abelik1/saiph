// SPDX-License-Identifier: AGPL-3.0-or-later
// Create an Ed25519 billing grant key pair (docs/PAID_HOSTED.md).
//   node scripts/billing-keygen.mjs <key id> <new private key file>
// The private key goes ONLY to a new owner-only file, for the account website's
// SAIPH_BILLING_GRANT_KEY. The public line is printed for the Hosted service's
// ORION_BILLING_GRANT_KEYS. Use separate keys for sandbox and live.
import { generateKeyPairSync } from "node:crypto";
import { closeSync, openSync, writeSync, constants } from "node:fs";

const [keyId, output] = process.argv.slice(2);
if (!keyId || !/^[a-z0-9-]{1,32}$/.test(keyId) || !output) {
  console.error("Usage: node scripts/billing-keygen.mjs <key id, e.g. sandbox-2026-10> <new private key file>");
  process.exit(2);
}
const { privateKey, publicKey } = generateKeyPairSync("ed25519");
// Exclusive creation: never overwrite an existing key file.
const descriptor = openSync(output, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600);
try {
  writeSync(descriptor, privateKey.export({ format: "der", type: "pkcs8" }).toString("base64url") + "\n");
} finally {
  closeSync(descriptor);
}
console.log("Private key written to the new file (keep it out of Git, chat and logs).");
console.log("SAIPH_BILLING_GRANT_KEY_ID=" + keyId);
console.log("Hosted service public key entry: " + keyId + ":" + publicKey.export({ format: "jwk" }).x);
