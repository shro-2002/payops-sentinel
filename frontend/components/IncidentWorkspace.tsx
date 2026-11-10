"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiPost, useApi, type ApiError } from "@/lib/api";
import { INVESTIGATION_STATE, investigationData } from "@/lib/studio-reports";
import type { Capture, Evidence, IncidentCommand, IncidentDetail, Investigation, Proposal } from "@/lib/types";
import { setWorkspace } from "@/lib/workspace-store";

import { AuditGrid } from "./AuditGrid";
import { CohortPanel, ResponsePlanPanel } from "./CohortAndPlan";
import { ConfirmButton } from "./ConfirmButton";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { CommandSummary, HypothesesPanel } from "./IncidentCommand";
import { IncidentHeader } from "./IncidentHeader";
import { ProposalsPanel, type ProposalInput } from "./ProposalsPanel";
import { RemediationPanel } from "./RemediationPanel";
import { ErrorState, Loading } from "./States";

const StudioCanvas = dynamic(() => import("./studio/StudioCanvas"), {
  ssr: false,
  loading: () => <Loading label="AG Studio workspace" />,
});

function pickDefaultRun(runs: Investigation[]): Investigation | null {
  return runs.find((r) => r.status === "COMPLETED" && r.finding) ?? runs[0] ?? null;
}

export function IncidentWorkspace({ id }: { id: string }) {
  const incident = useApi<IncidentDetail>(`incidents/${id}`);
  const command = useApi<IncidentCommand>(`incidents/${id}/command`);
  const txns = useApi<Capture[]>("transactions?limit=2000");
  const [runId, setRunId] = useState<string | null>(null);
  const [openEvidence, setOpenEvidence] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);

  const inc = incident.data;
  const runs = useMemo(() => inc?.investigations ?? [], [inc]);
  const run = runs.find((r) => r.id === runId) ?? pickDefaultRun(runs);

  useEffect(() => {
    setWorkspace({ investigation: run, proposals: inc?.proposals ?? [], openEvidence: setOpenEvidence });
  }, [run, inc]);

  const studioData = useMemo(
    () => (inc ? investigationData(txns.data ?? [], inc.window_start, inc.window_end, run) : null),
    [inc, txns.data, run],
  );

  const act = useCallback(
    async (label: string, fn: () => Promise<unknown>, success: string) => {
      setBusy(label);
      setNotice(null);
      try {
        await fn();
        setNotice({ kind: "ok", text: success });
      } catch (e) {
        const err = e as ApiError;
        setNotice({ kind: "bad", text: `${label} failed: ${err.message} (${err.code})` });
      } finally {
        setBusy(null);
        incident.reload();
        command.reload();
      }
    },
    [incident, command],
  );

  if (incident.error && !inc) return <ErrorState error={incident.error} onRetry={incident.reload} what="incident" />;
  if (!inc) return <Loading label="incident" />;

  const runInvestigation = (mode: "AI" | "BASELINE") =>
    act(`${mode} investigation`, () => apiPost(`incidents/${inc.id}/investigations`, { mode }), `${mode} investigation finished.`);
  const draft = (caseRef: string) =>
    act("AI draft", () => apiPost(`remediation-cases/${encodeURIComponent(caseRef)}/draft-proposal`), `Draft for ${caseRef} created and policy-evaluated.`);
  const propose = (input: ProposalInput) => act("Proposal", () => apiPost("proposals", { incident_id: inc.id, ...input }), "Proposal submitted.");
  const decide = (p: Proposal, approve: boolean) =>
    act(approve ? "Approval" : "Rejection", () => apiPost(`proposals/${p.id}/decision`, { approve, details_hash: p.details_hash }), approve ? "Approved." : "Rejected.");
  const execute = (p: Proposal) => act("Execution", () => apiPost(`proposals/${p.id}/execute`), "Execution submitted; see outcome below.");
  const verify = (exId: string) => act("Verification", () => apiPost(`executions/${exId}/verify`), "Verification complete.");

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="text-sm text-fg-muted">
        <Link href="/" className="hover:text-accent">
          Incidents
        </Link>{" "}
        / <span className="font-mono">{inc.id.slice(0, 8)}</span>
      </nav>

      <IncidentHeader incident={inc} proposals={inc.proposals} />

      {command.data && <CommandSummary cmd={command.data} />}
      {command.error && !command.data && <ErrorState error={command.error} onRetry={command.reload} what="incident command" />}

      <div aria-live="polite">
        {busy && (
          <p role="status" className="panel border-accent/40 p-3 text-sm text-accent">
            {busy} in progress…
          </p>
        )}
        {notice && <p className={`panel p-3 text-sm ${notice.kind === "ok" ? "border-ok/40 text-ok" : "border-bad/40 text-bad"}`}>{notice.text}</p>}
      </div>

      <section aria-labelledby="runs-h" className="panel flex flex-wrap items-center gap-3 p-4">
        <h2 id="runs-h" className="panel-title">
          Investigation runs
        </h2>
        <label className="flex items-center gap-2 text-sm">
          <span className="sr-only">Selected run</span>
          <select className="field w-auto" value={run?.id ?? ""} onChange={(e) => setRunId(e.target.value)}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.mode === "REPLAY" ? "REPLAYED (recorded Claude run)" : r.mode} · {r.status} · {r.tool_calls_used} calls ·{" "}
                {r.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        {run?.finding && (
          <span className="text-sm text-fg-muted">
            AI-named driver{" "}
            <span className="font-mono text-fg">
              {run.finding.root_cause ? `${run.finding.root_cause.dimension}=${run.finding.root_cause.value}` : "none"}
            </span>{" "}
            (a hypothesis until the server challenge supports it) ·{" "}
            · confidence {run.finding.confidence} · recommends {run.finding.recommended_action}
          </span>
        )}
        {run?.mode === "REPLAY" && (
          <span className="badge badge-warn" role="note">
            Replayed: recorded {run.model?.replace("replay:", "")} transcript, tool queries re-run live, claims re-verified
          </span>
        )}
        {run?.error && <span className="max-w-xl truncate text-xs text-bad" title={run.error}>{run.error}</span>}
        <div className="ml-auto flex gap-2">
          <ConfirmButton
            label="Run baseline"
            title="Run the deterministic baseline investigator?"
            body="Runs the non-LLM baseline over the same read-only tools. No LLM quota is used."
            confirmLabel="Run baseline"
            disabled={!!busy}
            onConfirm={() => runInvestigation("BASELINE")}
          />
          <ConfirmButton
            label="Run AI investigation"
            title="Start a new AI investigation?"
            body="Runs one live LLM investigation with read-only tools (about 30 seconds). Existing runs are kept."
            confirmLabel="Run AI investigation"
            variant="primary"
            disabled={!!busy}
            onConfirm={() => runInvestigation("AI")}
          />
        </div>
      </section>

      {run?.finding && (
        <section aria-labelledby="finding-h" className="panel grid gap-3 p-4 md:grid-cols-2">
          <h2 id="finding-h" className="panel-title md:col-span-2">
            Finding (AI narrative — trust only the verified claims)
          </h2>
          <p className="text-sm">
            <span className="text-fg-faint">Hypothesis. </span>
            {run.finding.hypothesis}
          </p>
          <p className="text-sm">
            <span className="text-fg-faint">Uncertainty. </span>
            {run.finding.uncertainty}
          </p>
        </section>
      )}

      {command.data && (
        <>
          <HypothesesPanel cmd={command.data} />
          <div className="grid gap-4 xl:grid-cols-2">
            <CohortPanel cmd={command.data} />
            <ResponsePlanPanel cmd={command.data} />
          </div>
        </>
      )}

      {studioData && (
        <StudioCanvas storageKey="payops.studio.investigation.v1" label="Investigation workspace" data={studioData} initialState={INVESTIGATION_STATE} height={1250} />
      )}
      {txns.error && <ErrorState error={txns.error} onRetry={txns.reload} what="transactions" />}

      <div className="grid gap-4 xl:grid-cols-2">
        <RemediationPanel cases={inc.remediation_cases} busy={!!busy} onDraft={draft} />
        <ProposalsPanel proposals={inc.proposals} cases={inc.remediation_cases} busy={!!busy} onPropose={propose} onDecide={decide} onExecute={execute} onVerify={verify} />
      </div>

      <AuditGrid audit={inc.audit} />

      <EvidenceDrawer evidence={openEvidence} onClose={() => setOpenEvidence(null)} />
    </div>
  );
}
