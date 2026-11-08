"use client";

import { useState, type FormEvent } from "react";

import type { Proposal, RemediationCase } from "@/lib/types";

import { ConfirmButton } from "./ConfirmButton";

const AMOUNT_RE = /^\d{1,7}\.\d{2}$/;
const CURRENCY_RE = /^[A-Z]{3}$/;

export interface ProposalInput {
  action_type: Proposal["action_type"];
  reason: string;
  target_capture_id?: string;
  amount?: string;
  currency?: string;
  case_ref?: string;
}

interface Props {
  proposals: Proposal[];
  cases: RemediationCase[];
  busy: boolean;
  onPropose: (input: ProposalInput) => void;
  onDecide: (p: Proposal, approve: boolean) => void;
  onExecute: (p: Proposal) => void;
  onVerify: (executionId: string) => void;
}

function statusBadge(status: string) {
  if (["EXECUTED", "APPROVED", "POLICY_PASSED"].includes(status)) return "badge badge-ok";
  if (status.includes("REJECTED") || status.includes("FAILED") || status === "APPROVAL_INVALID") return "badge badge-bad";
  return "badge badge-warn";
}

function ManualProposalForm({ cases, busy, onPropose }: Pick<Props, "cases" | "busy" | "onPropose">) {
  const [action, setAction] = useState<Proposal["action_type"]>("MANUAL_REVIEW");
  const [reason, setReason] = useState("");
  const [caseRef, setCaseRef] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const linked = cases.find((c) => c.case_ref === caseRef);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason.trim().length < 5) return setError("Give a reason (at least 5 characters).");
    if (action === "PARTIAL_REFUND") {
      if (!linked) return setError("A partial refund must reference a remediation case.");
      if (!AMOUNT_RE.test(amount)) return setError('Amount must look like "12.00".');
      if (!CURRENCY_RE.test(linked.currency)) return setError("Case currency is invalid.");
    }
    setError(null);
    onPropose({
      action_type: action,
      reason: reason.trim(),
      ...(action === "PARTIAL_REFUND" && linked
        ? { target_capture_id: linked.capture_id, amount, currency: linked.currency, case_ref: linked.case_ref }
        : {}),
    });
  };

  return (
    <form onSubmit={submit} className="mt-3 grid gap-2 rounded-md border border-line bg-ink-950 p-3 md:grid-cols-3" aria-labelledby="manual-h">
      <h3 id="manual-h" className="panel-title md:col-span-3">
        Manual proposal (operator)
      </h3>
      <label className="text-xs text-fg-muted">
        Action
        <select className="field mt-1" value={action} onChange={(e) => setAction(e.target.value as Proposal["action_type"])}>
          <option value="NO_ACTION">NO_ACTION</option>
          <option value="MANUAL_REVIEW">MANUAL_REVIEW</option>
          <option value="PARTIAL_REFUND">PARTIAL_REFUND</option>
        </select>
      </label>
      <label className="text-xs text-fg-muted">
        Remediation case
        <select className="field mt-1" value={caseRef} onChange={(e) => setCaseRef(e.target.value)} disabled={action !== "PARTIAL_REFUND"}>
          <option value="">—</option>
          {cases.map((c) => (
            <option key={c.case_ref} value={c.case_ref}>
              {c.case_ref} ({c.capture_id})
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-fg-muted">
        Amount {linked ? `(${linked.currency}, requested ${linked.requested})` : ""}
        <input className="field mt-1 font-mono" inputMode="decimal" placeholder="12.00" value={amount} onChange={(e) => setAmount(e.target.value)} disabled={action !== "PARTIAL_REFUND"} />
      </label>
      <label className="text-xs text-fg-muted md:col-span-3">
        Reason
        <input className="field mt-1" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} placeholder="Why this action is justified by case data" />
      </label>
      <div className="flex items-center gap-3 md:col-span-3">
        <button type="submit" className="btn btn-ghost" disabled={busy}>
          Submit for policy evaluation
        </button>
        {error && (
          <p role="alert" className="text-xs text-bad">
            {error}
          </p>
        )}
      </div>
    </form>
  );
}

function ProposalCard({ p, busy, onDecide, onExecute, onVerify }: { p: Proposal } & Pick<Props, "busy" | "onDecide" | "onExecute" | "onVerify">) {
  const isMoney = p.action_type === "PARTIAL_REFUND";
  const approvalSummary = (
    <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 font-mono text-xs text-fg">
      <dt className="text-fg-faint">Action</dt>
      <dd>{p.action_type}</dd>
      <dt className="text-fg-faint">Amount</dt>
      <dd>{p.amount ? `${p.amount} ${p.currency}` : "—"}</dd>
      <dt className="text-fg-faint">Target capture</dt>
      <dd>{p.target_capture_id ?? "—"}</dd>
      <dt className="text-fg-faint">Case</dt>
      <dd>{p.case_ref ?? "—"}</dd>
      <dt className="text-fg-faint">Details hash</dt>
      <dd>{p.details_hash.slice(0, 16)}…</dd>
    </dl>
  );
  const ex = p.execution;
  return (
    <li className="rounded-md border border-line bg-ink-950 p-3" data-testid="proposal-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">{p.action_type}</span>
        {p.amount && (
          <span className="font-mono text-sm">
            {p.amount} {p.currency}
          </span>
        )}
        <span className={statusBadge(p.status)}>{p.status}</span>
        <span className="badge badge-neutral">by {p.proposed_by}</span>
        <span className="ml-auto font-mono text-[11px] text-fg-faint">
          {p.case_ref ?? "no case"} · {p.target_capture_id ?? "no target"} · hash {p.details_hash.slice(0, 10)}
        </span>
      </div>
      <p className="mt-1 text-sm text-fg-muted">{p.reason}</p>

      {p.policy && (
        <details className="mt-2" open={!p.policy.passed}>
          <summary className="cursor-pointer text-xs text-fg-muted">
            Policy: {p.policy.passed ? "all" : "not all"} {p.policy.checks.length} checks {p.policy.passed ? "passed" : `— ${p.policy.checks.filter((c) => !c.passed).length} failed`}
          </summary>
          <ul className="mt-1 grid gap-x-4 text-xs md:grid-cols-2">
            {p.policy.checks.map((c) => (
              <li key={c.name} className="flex gap-2">
                <span className={c.passed ? "w-9 font-semibold text-ok" : "w-9 font-semibold text-bad"}>{c.passed ? "PASS" : "FAIL"}</span>
                <span className="font-mono">{c.name}</span>
                <span className="truncate text-fg-faint" title={c.detail}>
                  {c.detail}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {p.status === "POLICY_PASSED" && (
          <>
            <ConfirmButton
              label="Approve"
              title="Approve exactly this action?"
              body={
                <>
                  <p className="mb-2">Your approval is bound to this details hash. If any detail changes, it becomes invalid.</p>
                  {approvalSummary}
                </>
              }
              confirmLabel={isMoney ? `Approve ${p.amount} ${p.currency}` : "Approve"}
              variant="primary"
              disabled={busy}
              onConfirm={() => onDecide(p, true)}
              testId="approve-btn"
            />
            <ConfirmButton label="Reject" title="Reject this proposal?" body={approvalSummary} confirmLabel="Reject" variant="danger" disabled={busy} onConfirm={() => onDecide(p, false)} />
          </>
        )}
        {p.status === "APPROVED" && isMoney && (
          <ConfirmButton
            label="Execute refund"
            title="Execute a real PayPal sandbox refund?"
            body={
              <>
                <p className="mb-2">The server re-validates policy against fresh provider state before moving money.</p>
                {approvalSummary}
              </>
            }
            confirmLabel={`Refund ${p.amount} ${p.currency}`}
            variant="danger"
            disabled={busy}
            onConfirm={() => onExecute(p)}
          />
        )}
        {ex && ex.status !== "VERIFIED" && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => onVerify(ex.id)}>
            Verify with PayPal
          </button>
        )}
      </div>

      {ex && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded border border-line p-2 text-xs" aria-label="Execution outcome">
          <span className="panel-title">Execution</span>
          <span className={ex.status === "VERIFIED" ? "badge badge-ok" : ex.status === "FAILED" ? "badge badge-bad" : "badge badge-warn"}>
            {ex.status === "VERIFIED" ? "VERIFIED" : ex.status === "FAILED" ? "FAILED" : `UNVERIFIED (${ex.status})`}
          </span>
          {ex.verified_at_paypal && (
            <span className="badge badge-ok" title={`Confirmed by PayPal (${ex.verified_via ?? "read-back"})`}>
              ✓ Verified at PayPal · {ex.verified_via === "paypal_webhook" ? "signed webhook" : "GET read-back"}
            </span>
          )}
          <span className="font-mono">refund id {ex.provider_refund_id ?? "—"}</span>
          <span className="font-mono">provider {ex.provider_status ?? "—"}</span>
          {ex.verified_at && <span className="font-mono text-fg-faint">verified {ex.verified_at}</span>}
          {ex.error && <span className="text-bad">{ex.error}</span>}
        </div>
      )}
    </li>
  );
}

export function ProposalsPanel({ proposals, cases, busy, onPropose, onDecide, onExecute, onVerify }: Props) {
  return (
    <section aria-labelledby="proposals-h" className="panel p-4">
      <h2 id="proposals-h" className="panel-title">
        Action proposals · {proposals.length}
      </h2>
      {proposals.length === 0 && <p className="mt-3 text-sm text-fg-muted">No proposals yet.</p>}
      <ul className="mt-3 space-y-3">
        {proposals.map((p) => (
          <ProposalCard key={p.id} p={p} busy={busy} onDecide={onDecide} onExecute={onExecute} onVerify={onVerify} />
        ))}
      </ul>
      <ManualProposalForm cases={cases} busy={busy} onPropose={onPropose} />
    </section>
  );
}
