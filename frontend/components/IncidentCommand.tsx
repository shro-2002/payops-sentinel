import type { HypothesisStatus, HypothesisTest, IncidentCommand, Slice } from "@/lib/types";

const pct = (r: number) => `${(r * 100).toFixed(1)}%`;
export const human = (s: string) => s.replace(/_/g, " ");
export const sliceLabel = (s: Slice) => `${s.dimension}=${s.value}`;

export function toneFor(status: string): string {
  if (/VERIFIED|SUPPORTED|FOUND|RESOLVED$/.test(status) && !/UNRESOLVED|NO_/.test(status)) return "badge-ok";
  if (/CONTRADICTED|FAILED|REJECTED/.test(status)) return "badge-bad";
  if (/OPEN|PENDING|MANUAL|UNRESOLVED|INSUFFICIENT/.test(status)) return "badge-warn";
  return "badge-neutral";
}

function StatusChip({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <li className="rounded-md border border-line bg-ink-950 p-3" data-testid={testId}>
      <p className="panel-title">{label}</p>
      <p className="mt-1">
        <span className={`badge ${toneFor(value)}`}>{human(value)}</span>
      </p>
    </li>
  );
}

export function CommandSummary({ cmd }: { cmd: IncidentCommand }) {
  const s = cmd.statuses;
  const cases = Object.entries(s.paypal_execution.cases)
    .map(([k, n]) => `${n} ${k.toLowerCase()}`)
    .join(" · ");
  return (
    <section aria-labelledby="command-h" className="panel p-4" data-testid="incident-command">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="command-h" className="text-base font-semibold tracking-tight">
          Incident command
        </h2>
        <span className={`badge ${toneFor(s.incident)}`}>Incident {human(s.incident)}</span>
      </div>
      <ul className="mt-3 grid gap-3 sm:grid-cols-3" aria-label="Independent statuses">
        <StatusChip testId="status-investigation" label="Investigation" value={s.investigation} />
        <StatusChip testId="status-operational" label="Operational response" value={s.operational_response} />
        <li className="rounded-md border border-line bg-ink-950 p-3" data-testid="status-paypal">
          <p className="panel-title">PayPal execution (refund cases)</p>
          <p className="mt-1 flex flex-wrap items-center gap-2">
            <span className={`badge ${toneFor(s.paypal_execution.status)}`}>{human(s.paypal_execution.status)}</span>
            <span className="font-mono text-xs text-fg-muted">{cases}</span>
          </p>
        </li>
      </ul>
      <p className="mt-3 text-sm text-fg-muted" role="note">
        {s.note}
      </p>
    </section>
  );
}

const STATUS_TEXT: Record<HypothesisStatus, string> = {
  ASSOCIATION_SUPPORTED: "Supported (association)",
  UNRESOLVED: "Unresolved",
  INSUFFICIENT_EVIDENCE: "Too few samples",
  CONTRADICTED: "Contradicted",
};
const ORDER: HypothesisStatus[] = ["ASSOCIATION_SUPPORTED", "UNRESOLVED", "INSUFFICIENT_EVIDENCE", "CONTRADICTED"];

function Relations({ t }: { t: HypothesisTest }) {
  const parts = [
    t.explained_by && `explained by ${sliceLabel(t.explained_by)}`,
    t.refined_to && `refined to ${sliceLabel(t.refined_to)}`,
    t.indistinguishable_from && `can't separate from ${sliceLabel(t.indistinguishable_from)}`,
    t.conditional_on_excluding?.length && `tested outside ${t.conditional_on_excluding.map(sliceLabel).join(", ")}`,
  ].filter(Boolean);
  if (!parts.length) return null;
  return <p className="mt-1 font-mono text-xs text-accent">{parts.join(" · ")}</p>;
}

function HypothesisRow({ t }: { t: HypothesisTest }) {
  const sl = t.slice;
  return (
    <li className="rounded-md border border-line bg-ink-950 p-3" data-testid="hypothesis-row">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`badge ${toneFor(t.status)}`}>{STATUS_TEXT[t.status] ?? human(t.status)}</span>
        <span className="font-mono text-sm font-semibold">{sliceLabel(t.hypothesis)}</span>
        {sl && (
          <span className="font-mono text-xs text-fg-muted sm:ml-auto">
            refund rate <span className="text-fg">{pct(sl.rate)}</span> vs rest {pct(sl.comparison.rate)} (z {sl.z_vs_rest}) vs own
            baseline {pct(sl.own_baseline.rate)} · {sl.refunds}/{sl.captures} captures
          </span>
        )}
      </div>
      <Relations t={t} />
      <p className="mt-1 text-xs text-fg-muted">{t.reason}</p>
    </li>
  );
}

export function HypothesesPanel({ cmd }: { cmd: IncidentCommand }) {
  const tests = [...cmd.challenger.tests].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return (
    <section aria-labelledby="hyp-h" className="panel p-4">
      <h2 id="hyp-h" className="panel-title">
        Competing hypotheses · {tests.length} tested
      </h2>
      <p className="mt-1 text-sm text-fg-muted">
        A deterministic challenger generates candidates in every dimension (and separately re-tests every driver the AI
        names), then tries to disprove each one: an exact lift test vs the rest of the window and vs its own baseline,
        corrected for every value scanned, then persistence within every other dimension. Supported means a suspected
        contributing factor, not a proven root cause.
      </p>
      {tests.length === 0 && <p className="mt-3 text-sm text-fg-muted">No hypotheses tested yet. Run an investigation.</p>}
      <ol className="mt-3 space-y-2">
        {tests.map((t) => (
          <HypothesisRow key={sliceLabel(t.hypothesis)} t={t} />
        ))}
      </ol>
    </section>
  );
}


