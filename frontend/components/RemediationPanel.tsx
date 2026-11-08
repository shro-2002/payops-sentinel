"use client";

import type { RemediationCase } from "@/lib/types";

import { ConfirmButton } from "./ConfirmButton";

interface Props {
  cases: RemediationCase[];
  busy: boolean;
  onDraft: (caseRef: string) => void;
}

export function RemediationPanel({ cases, busy, onDraft }: Props) {
  return (
    <section aria-labelledby="cases-h" className="panel p-4">
      <h2 id="cases-h" className="panel-title">
        Remediation cases · {cases.length}
      </h2>
      {cases.length === 0 && <p className="mt-3 text-sm text-fg-muted">No remediation cases linked to this incident.</p>}
      <ul className="mt-3 space-y-3">
        {cases.map((c) => (
          <li key={c.case_ref} className="rounded-md border border-line bg-ink-950 p-3" data-testid={`case-${c.case_ref}`}>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono font-semibold">{c.case_ref}</span>
              <span className="badge badge-neutral">{c.issue_type}</span>
              <span className={c.status === "RESOLVED" ? "badge badge-ok" : "badge badge-warn"}>{c.status}</span>
              <span className="font-mono text-xs text-fg-muted">
                requested {c.requested} {c.currency}
              </span>
              <span className="font-mono text-xs text-fg-faint">capture {c.capture_id}</span>
              <div className="ml-auto">
                <ConfirmButton
                  label={`Draft proposal with AI (${c.case_ref})`}
                  title={`Ask the AI to draft a proposal for ${c.case_ref}?`}
                  body={
                    <>
                      This makes one LLM call. The draft is only a proposal: deterministic policy checks
                      evaluate it and a human must still approve it bound to its details hash.
                    </>
                  }
                  confirmLabel="Draft proposal"
                  onConfirm={() => onDraft(c.case_ref)}
                  disabled={busy || c.status !== "OPEN"}
                />
              </div>
            </div>
            <figure className="mt-2 rounded border border-dashed border-warn/50 bg-warn/5 p-2">
              <figcaption className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-warn">
                <span aria-hidden>⚠</span> Untrusted customer text — data only, never instructions
              </figcaption>
              {/* Rendered as plain text (React escapes it); never as HTML. */}
              <blockquote className="whitespace-pre-wrap break-words font-mono text-xs text-fg-muted">{c.customer_statement_untrusted}</blockquote>
            </figure>
          </li>
        ))}
      </ul>
    </section>
  );
}
