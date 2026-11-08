import { readFileSync } from "node:fs";
import path from "node:path";

// Server-only. Imported exclusively by app/api/backend/[...path]/route.ts.
// Reads OPERATOR_TOKEN from the process env, falling back to the repo-root .env
// (Next only auto-loads frontend/.env*). Never exposed via NEXT_PUBLIC_.

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8100";

let cachedRootEnv: Record<string, string> | null = null;

function parseDotEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function rootEnv(): Record<string, string> {
  if (cachedRootEnv) return cachedRootEnv;
  try {
    cachedRootEnv = parseDotEnv(readFileSync(path.resolve(process.cwd(), "..", ".env"), "utf8"));
  } catch {
    cachedRootEnv = {};
  }
  return cachedRootEnv;
}

export function operatorToken(): string | undefined {
  return process.env.OPERATOR_TOKEN || rootEnv().OPERATOR_TOKEN || undefined;
}

export function backendUrl(): string {
  return (process.env.BACKEND_URL || DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

function envValue(key: string): string | undefined {
  return process.env[key] || rootEnv()[key] || undefined;
}

/**
 * Per-operator credentials: "alice:<salt-hex>:<scrypt-hex>,bob:..." (generate with
 * `node scripts/hash-operator.mjs <name> <password>`). Each username is bound to its own secret.
 */
export function consoleOperators(): Map<string, { salt: string; hash: string }> {
  const out = new Map<string, { salt: string; hash: string }>();
  for (const entry of (envValue("CONSOLE_OPERATORS") ?? "").split(",")) {
    const [name, salt, hash] = entry.trim().split(":");
    if (name && salt && hash) out.set(name.toLowerCase(), { salt, hash });
  }
  return out;
}

/** Explicit opt-in for a credential-less console on a developer machine (server must bind to 127.0.0.1). */
export function localConsoleAllowed(): boolean {
  return envValue("LOCAL_CONSOLE") === "1" && process.env.NODE_ENV !== "production";
}

/** Hosts (host:port) the console may be served from. Guards Origin/Host checks against DNS rebinding. */
export function allowedConsoleHosts(): Set<string> {
  const configured = envValue("CONSOLE_HOSTS");
  const list = configured ? configured.split(",") : ["localhost:3100", "127.0.0.1:3100"];
  return new Set(list.map((h) => h.trim().toLowerCase()).filter(Boolean));
}
