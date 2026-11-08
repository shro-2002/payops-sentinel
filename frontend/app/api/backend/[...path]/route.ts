import { NextRequest, NextResponse } from "next/server";

import { scryptSync, timingSafeEqual } from "node:crypto";

import { allowedConsoleHosts, backendUrl, consoleOperators, localConsoleAllowed, operatorToken } from "@/lib/server-env";

export const dynamic = "force-dynamic";

const ID = "[A-Za-z0-9_-]{1,64}";
const GET_ROUTES = [
  "incidents",
  `incidents/${ID}`,
  `evidence/${ID}/records`,
  `tool-calls/${ID}`,
  "transactions",
  "metrics/refund-trend",
  "events",
  "evaluation",
  "config",
  "studio/config",
].map((p) => new RegExp(`^${p}$`));
const POST_ROUTES = [
  `incidents/${ID}/investigations`,
  `remediation-cases/${ID}/draft-proposal`,
  "proposals",
  `proposals/${ID}/decision`,
  `proposals/${ID}/execute`,
  `executions/${ID}/verify`,
  "studio/llm",
].map((p) => new RegExp(`^${p}$`));
const ALLOWED_QUERY = new Set(["limit", "origin", "hours"]);
const MAX_BODY_BYTES = 16 * 1024;
// AI investigations take ~20s; leave headroom.
const UPSTREAM_TIMEOUT_MS = 90_000;

type Ctx = { params: Promise<{ path: string[] }> };

function fail(status: number, code: string, message: string) {
  return NextResponse.json({ detail: { code, message } }, { status });
}

function upstreamUrl(req: NextRequest, joined: string): string {
  const qs = new URLSearchParams();
  req.nextUrl.searchParams.forEach((v, k) => {
    if (ALLOWED_QUERY.has(k) && /^[A-Za-z0-9_.-]{1,32}$/.test(v)) qs.set(k, v);
  });
  const q = qs.toString();
  return `${backendUrl()}/api/v1/${joined}${q ? `?${q}` : ""}`;
}

async function forward(url: string, init: RequestInit) {
  try {
    const res = await fetch(url, { ...init, cache: "no-store", signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS) });
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json", "cache-control": "no-store" },
    });
  } catch {
    return fail(502, "BACKEND_UNREACHABLE", "The PayOps backend did not respond. Is it running?");
  }
}

export async function GET(req: NextRequest, ctx: Ctx) {
  const joined = (await ctx.params).path.join("/");
  if (!GET_ROUTES.some((r) => r.test(joined))) return fail(404, "ROUTE_NOT_ALLOWED", "Path is not proxied");
  // Reads return customer data and approval material: same operator gate as writes.
  const host = (req.headers.get("host") ?? "").toLowerCase();
  if (!allowedConsoleHosts().has(host)) return fail(403, "HOST_NOT_ALLOWED", "Console host is not allowlisted");
  const operator = authenticateOperator(req, host);
  if (!operator) return unauthenticated();
  const token = operatorToken();
  if (!token) return fail(503, "OPERATOR_TOKEN_MISSING", "OPERATOR_TOKEN is not configured on the console server");
  return forward(upstreamUrl(req, joined), {
    method: "GET",
    headers: { authorization: `Bearer ${token}`, "x-operator": operator },
  });
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const joined = (await ctx.params).path.join("/");
  if (!POST_ROUTES.some((r) => r.test(joined))) return fail(404, "ROUTE_NOT_ALLOWED", "Path is not proxied");

  // CSRF + DNS rebinding: the Host must be an allowlisted console host and the Origin must be present and equal it.
  const host = (req.headers.get("host") ?? "").toLowerCase();
  const origin = req.headers.get("origin");
  if (!allowedConsoleHosts().has(host)) return fail(403, "HOST_NOT_ALLOWED", "Console host is not allowlisted");
  if (!origin || safeHost(origin) !== host) return fail(403, "CROSS_ORIGIN", "Writes require a same-origin Origin header");
  if ((req.headers.get("content-type") ?? "").split(";")[0].trim() !== "application/json") {
    return fail(415, "JSON_REQUIRED", "Content-Type must be application/json");
  }
  // Operator authentication BEFORE the backend token is attached.
  const operator = authenticateOperator(req, host);
  if (!operator) return unauthenticated();
  const body = await req.text();
  if (body.length > MAX_BODY_BYTES) return fail(413, "BODY_TOO_LARGE", "Request body too large");

  const token = operatorToken();
  if (!token) return fail(503, "OPERATOR_TOKEN_MISSING", "OPERATOR_TOKEN is not configured on the console server");

  return forward(upstreamUrl(req, joined), {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}`, "x-operator": operator },
    body: body || "{}",
  });
}


function safeHost(url: string): string | null {
  try {
    return new URL(url).host.toLowerCase();
  } catch {
    return null;
  }
}

/**
 * Returns the authenticated operator name, or null. Never derived from request headers like Host: either the
 * caller presents its own credential, or the server operator explicitly opted into a local, credential-less dev
 * console (LOCAL_CONSOLE=1, non-production).
 */
function authenticateOperator(req: NextRequest, _host: string): string | null {
  const operators = consoleOperators();
  if (operators.size === 0) return localConsoleAllowed() ? "local-operator" : null;
  const header = req.headers.get("authorization") ?? "";
  if (!header.startsWith("Basic ")) return null;
  const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
  const sep = decoded.indexOf(":");
  if (sep <= 0) return null;
  const user = decoded.slice(0, sep).toLowerCase();
  const entry = operators.get(user);
  if (!entry || !/^[a-z0-9._-]{1,32}$/.test(user)) return null;
  const expected = Buffer.from(entry.hash, "hex");
  const actual = scryptSync(decoded.slice(sep + 1), Buffer.from(entry.salt, "hex"), expected.length || 32);
  return expected.length > 0 && actual.length === expected.length && timingSafeEqual(actual, expected) ? user : null;
}

function unauthenticated() {
  const res = fail(401, "UNAUTHENTICATED", "Operator login required");
  res.headers.set("WWW-Authenticate", 'Basic realm="PayOps Sentinel operator", charset="UTF-8"');
  return res;
}
