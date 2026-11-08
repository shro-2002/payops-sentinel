// Fails if any 8-char prefix of OPERATOR_TOKEN appears in the client build output.
// Reads the token from ../.env and never prints it.
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const env = readFileSync(path.resolve("..", ".env"), "utf8");
const line = env.split(/\r?\n/).find((l) => l.startsWith("OPERATOR_TOKEN="));
const token = line?.slice("OPERATOR_TOKEN=".length).trim().replace(/^['"]|['"]$/g, "");
if (!token || token.length < 8) {
  console.error("OPERATOR_TOKEN not found in ../.env");
  process.exit(2);
}
const needle = token.slice(0, 8);
const roots = [".next/static", ".next/server/app"].filter((p) => {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
});
let hits = 0;
let scanned = 0;
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else {
      scanned++;
      if (readFileSync(p).includes(needle)) {
        hits++;
        console.error(`LEAK: token prefix found in ${p}`);
      }
    }
  }
};
roots.forEach(walk);
console.log(`scanned ${scanned} files in ${roots.join(", ")}: ${hits ? "FAIL" : "PASS (token prefix absent)"}`);
process.exit(hits ? 1 : 0);
