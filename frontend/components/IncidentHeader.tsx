import type { Incident, Proposal } from "@/lib/types";

const pct = (r: number) => `${(r * 100).toFixed(1)}%`;

function Milestone({ label, done, detail, testId }: { label: string; done: boolean; detail: string; testId: string }) {
  return (
    <li className={`rounded-md border p-3 ${done ? "border-ok/40 bg-ok/5" : "border-line bg-ink-950"}`} data-testid={testId}>
      <div className="flex items-center gap-2">
        <span className={done ? "badge badge-ok" : "badge badge-neutral"}>{done ? "Yes" : "Not yet"}</span>
        <span className="text-sm font-semibold">{label}</span>
      </div>
      <p className="mt-1 text-xs text-fg-muted">{detail}</p>
    </li>
  );
}

export function IncidentHeader({ incident, proposals }: { incident: Incident; proposals: Proposal[] }) {
  const m = incident.metrics;
  const executed = proposals.filter((p) => p.status === "EXECUTED" && p.execution?.status === "VERIFIED");
  return (
    <section aria-labelledby="incident-title" className="panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge badge-bad">{incident.severity}</span>
        <span className="badge badge-neutral">{incident.detector}</span>
        <span className="badge badge-warn">{incident.status}</span>
        <span className="ml-auto font-mono text-xs text-fg-faint">
          window {incident.window_start} → {incident.window_end}
        </span>
      </div>
      <h1 id="incident-title" className="mt-2 text-xl font-semibold tracking-tight">
        {incident.title}
      </h1>

      <div className="mt-4 grid gap-3 md:grid-cols-[2fr,1fr]">
        <table className="w-full text-sm">
          <caption className="panel-title mb-2 text-left">
            Deterministic detector numbers
            {incident.created_at && (
              <span className="ml-2 font-mono text-xs font-normal normal-case text-fg-faint">
                detector snapshot (incident opened {incident.created_at}; recomputed if the synthetic history was reseeded) · investigation queries read the live ledger, so refunds
                recorded later in the same window show up there
              </span>
            )}
          </caption>
          <thead className="text-left text-xs text-fg-faint">
            <tr>
              <th scope="col" className="py-1 font-medium">Window</th>
              <th scope="col" className="font-medium">Captures</th>
              <th scope="col" className="font-medium">Refunds</th>
              <th scope="col" className="font-medium">Refund rate</th>
              <th scope="col" className="font-medium">Refunded (minor units)</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            <tr className="border-t border-line">
              <th scope="row" className="py-1 text-left font-sans font-medium">Current ({m.config.window_hours ?? "?"}h)</th>
              <td>{m.current.captures}</td>
              <td>{m.current.refunds}</td>
              <td className="font-semibold text-bad">{pct(m.current.rate)}</td>
              <td>{m.current.refunded_minor}</td>
            </tr>
            <tr className="border-t border-line">
              <th scope="row" className="py-1 text-left font-sans font-medium">Baseline ({m.config.baseline_days ?? "?"}d)</th>
              <td>{m.baseline.captures}</td>
              <td>{m.baseline.refunds}</td>
              <td>{pct(m.baseline.rate)}</td>
              <td>{m.baseline.refunded_minor}</td>
            </tr>
          </tbody>
        </table>
        <div>
          <p className="panel-title mb-2">Detector checks · ratio {m.ratio}×</p>
          <ul className="flex flex-wrap gap-2">
            {Object.entries(m.checks).map(([k, v]) => (
              <li key={k} className={v ? "badge badge-ok" : "badge badge-bad"}>
                {v ? "PASS" : "FAIL"} {k}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <ol className="mt-4 grid gap-3 md:grid-cols-3" aria-label="Incident milestones (independent states)">
        <Milestone
          testId="ms-driver"
          label="AI investigation: named driver confirmed"
          done={incident.root_cause_identified}
          detail={
            incident.root_cause_identified
              ? "A driver the AI named survived the server's falsification challenge. An association, not a proven root cause."
              : "No AI-named driver has passed the server's challenge yet (run an investigation). The independent challenger's own verdict is in Incident command below."
          }
        />
        <Milestone
          testId="ms-corrective"
          label="Individual refund cases settled"
          done={executed.length > 0}
          detail={
            executed.length
              ? `${executed.length} refund(s) executed and verified at PayPal. They settle individual customer cases; they do not resolve the incident.`
              : "No refund has been executed and verified at PayPal. Refunds settle individual cases, never the incident."
          }
        />
        <Milestone
          testId="ms-resolved"
          label="Aggregate incident resolved"
          done={incident.status === "RESOLVED"}
          detail="Only true once the detector sees the refund rate back within threshold. Refunds never mark the incident resolved."
        />
      </ol>
    </section>
  );
}
