"use client";

import { createAiHarness, directLlmRunner } from "ag-studio";
import type { AgAiAgentContext, AgAiHarnessSetup, AgAiParamsBuilder, AgAiTool, AgBuiltInAgentId, AgStudioApi } from "ag-studio";

import { apiGet, apiPost } from "@/lib/api";
import { payopsLlmAdapter } from "@/lib/studio-llm-adapter";
import type { EvidenceRecords, Incident, IncidentDetail, Investigation } from "@/lib/types";
import { getWorkspace, setWorkspace } from "@/lib/workspace-store";

// AG Studio AI assistant for PayOps: Studio's five built-in agents (lead fronts the chat) plus three PayOps tools
// that run in the browser against our backend through the same-origin console proxy.

const PANEL_HEIGHT = 22;
const PANELS = [
  { id: "payopsEvidence", type: "evidence-inspector", title: "Evidence Inspector", layout: { xTrack: 0, xSpan: 10 } },
  { id: "payopsTimeline", type: "investigation-timeline", title: "Investigation Timeline", layout: { xTrack: 10, xSpan: 7 } },
  { id: "payopsPolicy", type: "policy-decision", title: "Policy Decision", layout: { xTrack: 17, xSpan: 7 } },
] as const;
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_TEXT = 400;
const MAX_INVESTIGATIONS_PER_SESSION = 3;
let investigationsThisSession = 0;

const FENCE_ESCAPES: Record<string, string> = { "<": "\\u003c", ">": "\\u003e", "&": "\\u0026" };

/**
 * Tool output is data: fence it so the model treats customer/ledger text inside as untrusted, never as instructions.
 * <, > and & are JSON-escaped so nothing in the data can close the fence (the JSON still parses to the same value).
 */
function untrusted(payload: unknown): string {
  const json = JSON.stringify(payload).replace(/[<>&]/g, (c) => FENCE_ESCAPES[c]);
  return `<tool_data untrusted="true">\n${json}\n</tool_data>`;
}

interface Layout {
  xTrack: number;
  yTrack: number;
  xSpan: number;
  ySpan: number;
}
interface LoosePage {
  id: string;
  widgets: Record<string, { type: string }>;
  widgetLayout?: Record<string, Layout>;
}
interface LooseState {
  selectedPageId?: string;
  pages: LoosePage[];
}

const clip = (s: string | null | undefined, n = MAX_TEXT) => (s && s.length > n ? `${s.slice(0, n)}…` : (s ?? ""));

/**
 * Deterministically puts the three PayOps widgets on the selected page (top row, existing widgets pushed down).
 * Studio's agents can lay out widgets too, but our custom types expose no AI-configurable options, so we do not
 * rely on them for this. Returns the widget types that were added.
 */
function placePanels(api: AgStudioApi): string[] {
  const state = api.getState() as unknown as LooseState;
  const page = state.pages.find((p) => p.id === state.selectedPageId) ?? state.pages[0];
  if (!page) return [];
  const present = new Set(Object.values(page.widgets).map((w) => w.type));
  const missing = PANELS.filter((p) => !present.has(p.type));
  if (missing.length === 0) return [];
  const shifted = Object.fromEntries(
    Object.entries(page.widgetLayout ?? {}).map(([id, l]) => [id, { ...l, yTrack: l.yTrack + PANEL_HEIGHT }]),
  );
  const nextPage: LoosePage = {
    ...page,
    widgets: {
      ...page.widgets,
      ...Object.fromEntries(missing.map((p) => [p.id, { type: p.type, dataMapping: {}, format: { title: { enabled: true, text: p.title } } }])),
    },
    widgetLayout: { ...shifted, ...Object.fromEntries(missing.map((p) => [p.id, { ...p.layout, yTrack: 0, ySpan: PANEL_HEIGHT }])) },
  };
  const next = { ...state, pages: state.pages.map((p) => (p === page ? nextPage : p)) };
  api.setState(next as unknown as ReturnType<AgStudioApi["getState"]>, { source: { type: "ai", agent: "payops" } });
  return missing.map((p) => p.type);
}

async function resolveIncidentId(given: string | undefined): Promise<string> {
  if (given) {
    if (!ID_RE.test(given)) throw new Error("incident_id has an invalid format");
    return given;
  }
  const incidents = await apiGet<Incident[]>("incidents");
  const open = incidents.find((i) => i.status !== "RESOLVED" && i.status !== "CLOSED") ?? incidents[0];
  if (!open) throw new Error("There are no incidents.");
  return open.id;
}

function summarise(inc: IncidentDetail, run: Investigation | null, placed: string[]) {
  const f = run?.finding;
  return {
    incident: { id: inc.id, title: inc.title, status: inc.status, window: `${inc.window_start} → ${inc.window_end}` },
    investigation: run && {
      id: run.id, mode: run.mode, status: run.status, model: run.model, tool_calls_used: run.tool_calls_used, error: clip(run.error),
    },
    finding: f && {
      driver: f.root_cause ? `${f.root_cause.dimension}=${f.root_cause.value}` : null,
      confidence: f.confidence,
      recommended_action: f.recommended_action,
      verified_claims: f.verified_claims,
      unsupported_claims: f.unsupported_claims,
      hypothesis: clip(f.hypothesis),
      claims: f.evidence.slice(0, 8).map((e) => ({ evidence_id: e.id, verification: e.verification, statement: clip(e.statement, 200) })),
    },
    widgets: placed.length ? `Added to the page: ${placed.join(", ")}` : "PayOps widgets already on the page now show this run",
  };
}

async function showRun(api: AgStudioApi, incidentId: string, runId?: string) {
  const inc = await apiGet<IncidentDetail>(`incidents/${encodeURIComponent(incidentId)}`);
  const run = inc.investigations.find((r) => (runId ? r.id === runId : r.status === "COMPLETED" && r.finding)) ?? null;
  setWorkspace({ ...getWorkspace(), investigation: run, proposals: inc.proposals });
  return summarise(inc, run, placePanels(api));
}

function payopsTools(api: AgStudioApi): AgAiTool[] {
  const incidentParam = (s: AgAiParamsBuilder) =>
    s.object({ incident_id: s.string({ description: "Incident UUID. Omit to use the open refund incident." }).optional() });
  return [
    api.defineAiTool({
      name: "investigate_incident",
      description:
        "Start a NEW AI investigation of a refund incident on the PayOps backend (read-only ledger tools, ~20-40 s, costs real LLM spend). " +
        "Call ONLY when the user explicitly asks to investigate or re-run an investigation. Shows the result in the PayOps widgets.",
      params: incidentParam,
      execute: async (args: { incident_id?: string }, ctx) => {
        if (investigationsThisSession >= MAX_INVESTIGATIONS_PER_SESSION) {
          return ctx.error(`Session limit reached (${MAX_INVESTIGATIONS_PER_SESSION} investigations). Reload the page to run more.`);
        }
        // A human must confirm every paid run in the browser: model output (or injected text it read) cannot start one.
        if (typeof window === "undefined" || !window.confirm("Start a new AI investigation of the open refund incident? This makes paid LLM calls (~$0.11).")) {
          return ctx.error("The operator declined to start a new investigation.");
        }
        investigationsThisSession += 1;
        try {
          const id = await resolveIncidentId(args.incident_id);
          const run = await apiPost<Investigation>(`incidents/${encodeURIComponent(id)}/investigations`, { mode: "AI" });
          return ctx.success(untrusted(await showRun(api, id, run.id)));
        } catch (e) {
          return ctx.error(`Investigation failed: ${(e as Error).message}`);
        }
      },
    }),
    api.defineAiTool({
      name: "get_finding",
      description: "Get the latest completed investigation finding for an incident (free, no new run) and show it in the PayOps widgets.",
      params: incidentParam,
      execute: async (args: { incident_id?: string }, ctx) => {
        try {
          return ctx.success(untrusted(await showRun(api, await resolveIncidentId(args.incident_id))));
        } catch (e) {
          return ctx.error(`Could not load the finding: ${(e as Error).message}`);
        }
      },
    }),
    api.defineAiTool({
      name: "explain_claim",
      description: "Explain one evidence claim: returns the stored tool result and the ledger rows that back it.",
      params: (s) => s.object({ evidence_id: s.string({ description: "evidence_id from a finding's claims" }) }),
      execute: async (args: { evidence_id: string }, ctx) => {
        if (!ID_RE.test(args.evidence_id)) return ctx.error("evidence_id has an invalid format");
        try {
          const r = await apiGet<EvidenceRecords>(`evidence/${encodeURIComponent(args.evidence_id)}/records`);
          return ctx.success(
            untrusted({
              query_id: r.query_id,
              filter: r.filter,
              tool_result: clip(JSON.stringify(r.tool_result), 800),
              ledger_rows: r.records.length,
              sample: r.records.slice(0, 5).map((c) => ({
                id: c.id, amount: c.amount, refunded: c.refunded, sku: c.product_sku, partner: c.fulfillment_partner, region: c.region, origin: c.origin,
              })),
            }),
          );
        } catch (e) {
          return ctx.error(`Could not load the claim: ${(e as Error).message}`);
        }
      },
    }),
  ];
}

// The PayOps system prompt (tool rules, verification labels, untrusted-fence rule) is server-owned: see
// SERVER_SYSTEM_PROMPT in backend/app/api/studio.py, which prepends it to every Studio turn.

export const payopsAi: AgAiHarnessSetup = ({ api: coreApi }) => {
  // The `ai` setup receives the core API type; at runtime it is the full browser AgStudioApi.
  const api = coreApi as AgStudioApi;
  return createAiHarness(api, ({ builtIn }) => {
    const extra = payopsTools(api);
    const lead = {
      ...builtIn.lead,
      tools: (ctx: AgAiAgentContext, p: unknown) => [...(builtIn.lead.tools?.(ctx, p) ?? []), ...extra],
      adapter: payopsLlmAdapter,
    };
    const ids = Object.keys(builtIn) as AgBuiltInAgentId[];
    return {
      agents: ids.map((id) => directLlmRunner(id === "lead" ? lead : { ...builtIn[id], adapter: payopsLlmAdapter })),
      primary: "lead",
      promptStarters: [
        { label: "Investigate the open incident", prompt: "Investigate the open refund incident" },
        { label: "Show the latest finding", prompt: "Show me the latest finding for the open refund incident" },
      ],
    };
  });
};
