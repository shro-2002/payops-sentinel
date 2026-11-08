// Prints an Ed25519 key pair for signed operator identity (four-eyes). Private key -> console server env only;
// public key -> backend env. Usage: node frontend/scripts/gen-identity-keys.mjs
import { generateKeyPairSync } from "node:crypto";

const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const b64 = (k, type) => k.export({ format: "der", type }).toString("base64");
console.log(`OPERATOR_IDENTITY_PRIVATE_KEY=${b64(privateKey, "pkcs8")}   # console (Next.js) server only`);
console.log(`OPERATOR_IDENTITY_PUBLIC_KEY=${b64(publicKey, "spki")}   # backend`);
