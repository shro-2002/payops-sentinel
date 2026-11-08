import type { Evidence } from "./types";

// Each badge says exactly what the server checked: a number matched its source, or a cause claim met / missed the
// "explains >= 25% of excess refunds" rule. "VERIFIED" alone would suggest the narrative was checked; it is not.
type Tone = "ok" | "bad" | "warn";
const LABELS: Record<Evidence["verification"], { text: (qid: string) => string; tone: Tone }> = {
  VERIFIED: { text: (q) => `VALUE MATCHES ${q}`, tone: "ok" },
  UNSUPPORTED: { text: (q) => `NOT IN ${q}`, tone: "bad" },
  CAUSE_VERIFIED: { text: () => "CAUSE · ≥25% OF EXCESS", tone: "ok" },
  NOT_CAUSE_VERIFIED: { text: () => "RULED OUT · <25% OF EXCESS", tone: "ok" },
  CONTRADICTED: { text: () => "CLAIMED CAUSE · <25% OF EXCESS", tone: "bad" },
  UNRESOLVED: { text: () => "RULED OUT · ≥25% OF EXCESS (UNCHECKED)", tone: "warn" },
};

export function evidenceBadge(e: Pick<Evidence, "verification" | "query_id">): { text: string; className: string } {
  const label = LABELS[e.verification] ?? LABELS.UNSUPPORTED;
  return { text: label.text(e.query_id), className: `badge badge-${label.tone}` };
}
