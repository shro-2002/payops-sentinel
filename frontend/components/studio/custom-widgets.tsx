"use client";

import { evidenceBadge } from "@/lib/evidence-label";
import { useWorkspace } from "@/lib/workspace-store";

// Real AG Studio custom widget components (registered via createWidgets.additionalTypes).
// Studio passes AgWidgetParams; these read investigation data from the workspace store instead.

function Empty({ text }: { text: string }) {
  return <p className="p-4 text-sm text-fg-muted">{text}</p>;
}

export function EvidenceInspectorWidget() {
  const { investigation, openEvidence } = useWorkspace();
  const finding = investigation?.finding;
  if (!finding) return <Empty text="No completed investigation with a finding yet." />;
  return (
    <div className="flex h-full flex-col overflow-hidden text-fg">
      <div className="flex items-center gap-3 border-b border-line px-3 py-2 text-xs">
        <span className="font-semibold uppercase tracking-wide text-fg-muted">Claims</span>
        <span className="badge badge-ok">{finding.verified_claims} verified</span>
        <span className={finding.unsupported_claims ? "badge badge-bad" : "badge badge-neutral"}>
          {finding.unsupported_claims} unsupported
        </span>
        <span className="ml-auto text-fg-faint">Select a claim to inspect the stored tool result and ledger rows</span>
      </div>
      <ul className="flex-1 divide-y divide-line overflow-auto" aria-label="Evidence-backed claims">
        {finding.evidence.map((e) => (
          <li key={e.id}>
            <button
              type="button"
              onClick={() => openEvidence(e)}
              className="claim-row group flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-ink-800 focus-visible:bg-ink-800"
              data-testid="claim-row"
            >
              <span className={`${evidenceBadge(e).className} shrink-0`}>
                {evidenceBadge(e).text}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm leading-snug">{e.statement}</span>
                <span className="mt-0.5 block font-mono text-[11px] text-fg-faint">
                  {e.query_id} · {e.metric_path} · claimed {e.claimed_value} · source {e.source_value ?? "—"}
                  {e.reason ? ` · ${e.reason}` : ""}
                </span>
              </span>
              <span aria-hidden className="text-fg-faint group-hover:text-accent">
                →
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function InvestigationTimelineWidget() {
  const { investigation } = useWorkspace();
  if (!investigation) return <Empty text="No investigation run selected." />;
  const calls = [...investigation.tool_calls].sort((a, b) => a.seq - b.seq);
  return (
    <div className="flex h-full flex-col overflow-hidden text-fg">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2 text-xs text-fg-muted">
        <span className="font-semibold uppercase tracking-wide">Read-only tool calls</span>
        <span className="font-mono">
          {investigation.tool_calls_used}/{investigation.max_tool_calls} budget
        </span>
        <span>{investigation.model ?? investigation.mode}</span>
        {investigation.latency_ms != null && <span>{(investigation.latency_ms / 1000).toFixed(1)}s</span>}
      </div>
      <ol className="flex-1 overflow-auto px-3 py-2" aria-label="Investigation timeline">
        {calls.length === 0 && <li className="text-sm text-fg-muted">No tool calls recorded.</li>}
        {calls.map((c) => (
          <li key={c.id} className="relative border-l border-line pb-3 pl-4 last:pb-0">
            <span
              aria-hidden
              className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full ${c.status === "OK" ? "bg-ok" : "bg-bad"}`}
            />
            <div className="flex flex-wrap items-baseline gap-2 text-sm">
              <span className="font-mono text-xs text-accent">{c.query_id}</span>
              <span className="font-mono">{c.tool}</span>
              <span className={c.status === "OK" ? "badge badge-ok" : "badge badge-bad"}>{c.status}</span>
            </div>
            <div className="font-mono text-[11px] text-fg-faint">{JSON.stringify(c.arguments)}</div>
            {c.error && <div className="text-xs text-bad">{c.error}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function PolicyDecisionWidget() {
  const { proposals } = useWorkspace();
  const p = proposals[0];
  if (!p) return <Empty text="No action proposals yet. Draft one from a remediation case." />;
  const checks = p.policy?.checks ?? [];
  const failed = checks.filter((c) => !c.passed).length;
  return (
    <div className="flex h-full flex-col overflow-hidden text-fg">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-xs">
        <span className="font-semibold uppercase tracking-wide text-fg-muted">Latest proposal</span>
        <span className="font-mono">{p.action_type}</span>
        {p.amount && (
          <span className="font-mono">
            {p.amount} {p.currency}
          </span>
        )}
        {p.case_ref && <span className="font-mono">{p.case_ref}</span>}
        <span className={p.policy?.passed ? "badge badge-ok ml-auto" : "badge badge-bad ml-auto"}>
          {p.policy?.passed ? "POLICY PASSED" : `POLICY BLOCKED (${failed})`}
        </span>
      </div>
      <ul className="flex-1 overflow-auto px-3 py-1 text-sm" aria-label="Deterministic policy checks">
        {checks.map((c) => (
          <li key={c.name} className="flex items-baseline gap-2 py-0.5">
            <span className={c.passed ? "w-10 shrink-0 text-xs font-semibold text-ok" : "w-10 shrink-0 text-xs font-semibold text-bad"}>
              {c.passed ? "PASS" : "FAIL"}
            </span>
            <span className="font-mono text-xs">{c.name}</span>
            <span className="truncate text-xs text-fg-faint" title={c.detail}>
              {c.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
