import type { CohortGroup, CohortImpact, IncidentCommand, Money, PlanItem } from "@/lib/types";

import { human, sliceLabel, toneFor } from "./IncidentCommand";

const money = (m: Money) => `${m.value} ${m.currency}`;

function GroupFigures({ g }: { g: CohortGroup }) {
  const rows: [string, string | number][] = [
    ["Transactions", g.transactions],
    ["Customers", g.customers],
    ["Captured value (not a loss)", money(g.captured_value)],
    ["Refunded in window", money(g.refunded_in_window)],
    ["Remaining refundable", money(g.remaining_refundable)],
    ["Open customer cases", g.open_customer_cases],
  ];
  return (
    <div className="rounded-md border border-line bg-ink-950 p-3">
      <p className="flex flex-wrap items-center gap-2">
        <span className={g.basis.startsWith("ACTUAL") ? "badge badge-info" : "badge badge-neutral"}>{g.basis}</span>
        <span className="font-mono text-xs text-fg-faint">{g.currency}</span>
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-muted">{k}</dt>
            <dd className="text-right font-mono">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function CohortCard({ c }: { c: CohortImpact }) {
  return (
    <li className="space-y-2" data-testid="cohort-card">
      <h3 className="font-mono text-sm font-semibold">{sliceLabel(c.driver)}</h3>
      <div className="grid gap-2 md:grid-cols-2">
        {c.groups.map((g) => (
          <GroupFigures key={`${g.basis}-${g.currency}`} g={g} />
        ))}
      </div>
      {c.excess_estimate.map((e) => (
        <p key={e.currency} className="rounded-md border border-dashed border-warn/50 bg-warn/5 p-2 text-sm">
          <span className="badge badge-warn">SCENARIO ESTIMATE · not a measured loss</span>{" "}
          <span className="font-mono">
            ~{e.excess_refunds} excess refunds ≈ {money(e.excess_refund_value)}
          </span>{" "}
          <span className="text-xs text-fg-muted">({e.note})</span>
        </p>
      ))}
    </li>
  );
}

export function CohortPanel({ cmd }: { cmd: IncidentCommand }) {
  return (
    <section aria-labelledby="cohort-h" className="panel p-4">
      <h2 id="cohort-h" className="panel-title">
        Affected cohort &amp; exposure
      </h2>
      {cmd.impact.length === 0 && <p className="mt-3 text-sm text-fg-muted">No supported driver, so no cohort is sized.</p>}
      <ul className="mt-3 space-y-4">
        {cmd.impact.map((c) => (
          <CohortCard key={sliceLabel(c.driver)} c={c} />
        ))}
      </ul>
    </section>
  );
}

function RefundCaseDetail({ p }: { p: PlanItem }) {
  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs">
      <span className="font-mono text-fg-muted">
        capture {p.capture_id} · requested {p.requested} {p.currency}
      </span>
      {p.paypal?.refund_id && <span className="font-mono text-fg">PayPal refund {p.paypal.refund_id}</span>}
      {p.paypal?.verified_by_get && <span className="badge badge-ok">verified by GET</span>}
      <a href={`#case-${p.case_ref}`} className="text-accent underline-offset-2 hover:underline">
        Open {p.case_ref} in the approval flow
      </a>
    </p>
  );
}

function PlanRow({ p }: { p: PlanItem }) {
  const isRefund = p.type === "INDIVIDUAL_REFUND_CASE";
  return (
    <li className="rounded-md border border-line bg-ink-950 p-3" data-testid="plan-row">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`badge ${toneFor(p.status)}`}>{human(p.status)}</span>
        <span className="badge badge-neutral">{human(p.type)}</span>
        {!isRefund && !p.automated && <span className="text-xs text-warn">manual follow-up (no integration)</span>}
      </div>
      <p className="mt-1 text-sm">{p.action}</p>
      <p className="text-xs text-fg-muted">Why: {p.why}</p>
      {isRefund && <RefundCaseDetail p={p} />}
    </li>
  );
}

export function ResponsePlanPanel({ cmd }: { cmd: IncidentCommand }) {
  return (
    <section aria-labelledby="plan-h" className="panel p-4">
      <h2 id="plan-h" className="panel-title">
        Response plan · {cmd.response_plan.length}
      </h2>
      <ol className="mt-3 space-y-2">
        {cmd.response_plan.map((p, i) => (
          <PlanRow key={`${p.type}-${p.case_ref ?? i}`} p={p} />
        ))}
      </ol>
    </section>
  );
}
