import type { Evidence } from "./types";

// Each badge says exactly what the server checked. VERIFIED/UNSUPPORTED: a number matched (or not) its cited tool
// result. Statuses from the server's independent falsification challenge (query ids S1, S2, ...) test whether a driver
// the AI named survives; SUPPORTED means an association that survived, never a proven root cause. SHARE_* is the
// share of excess refunds a slice carries: informational only, not a driver test.
type Tone = "ok" | "bad" | "warn" | "neutral";
const LABELS: Record<Evidence["verification"], { text: (qid: string) => string; tone: Tone }> = {
  VERIFIED: { text: (q) => `VALUE MATCHES ${q}`, tone: "ok" },
  UNSUPPORTED: { text: (q) => `NOT IN ${q}`, tone: "bad" },
  ASSOCIATION_SUPPORTED: { text: () => "SERVER CHALLENGE · SUPPORTED", tone: "ok" },
  CONTRADICTED: { text: () => "SERVER CHALLENGE · CONTRADICTED", tone: "bad" },
  UNRESOLVED: { text: () => "SERVER CHALLENGE · UNRESOLVED", tone: "warn" },
  INSUFFICIENT_EVIDENCE: { text: () => "SERVER CHALLENGE · TOO FEW SAMPLES", tone: "warn" },
  SHARE_MATERIAL: { text: () => "SHARE ONLY (INFO)", tone: "neutral" },
  SHARE_IMMATERIAL: { text: () => "SHARE ONLY (INFO)", tone: "neutral" },
};

export function evidenceBadge(e: Pick<Evidence, "verification" | "query_id">): { text: string; className: string } {
  const label = LABELS[e.verification] ?? LABELS.UNSUPPORTED;
  return { text: label.text(e.query_id), className: `badge badge-${label.tone}` };
}
