// Usage: node scripts/hash-operator.mjs <name> <password>  -> prints one CONSOLE_OPERATORS entry
import { randomBytes, scryptSync } from "node:crypto";

const [name, password] = process.argv.slice(2);
if (!name || !password || !/^[a-zA-Z0-9._-]{1,32}$/.test(name)) {
  console.error("usage: node scripts/hash-operator.mjs <name> <password>");
  process.exit(1);
}
const salt = randomBytes(16);
console.log(`${name.toLowerCase()}:${salt.toString("hex")}:${scryptSync(password, salt, 32).toString("hex")}`);
