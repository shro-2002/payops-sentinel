"use client";

import { useCallback, useMemo, useState } from "react";

import { AgStudioAiModule, studioTheme } from "ag-studio";
import { AgStudio, AgStudioProvider, createWidgets } from "ag-studio-react";
import type { AgDataSourcesDefinition, AgDefaultWidgetDefinition, AgReportState, AgWidgetData, AgWidgetDataFormat } from "ag-studio";
import type { AgRegistry, AgWidgetDefinition } from "ag-studio-react";

import { useStudioConfig } from "@/lib/studio-config";

import { EvidenceInspectorWidget, InvestigationTimelineWidget, PolicyDecisionWidget } from "./custom-widgets";
import { payopsAi } from "./payops-ai";

// Custom PayOps widget state: no data mapping (data comes from the workspace store).
type PanelState<T extends string> = AgWidgetData<Record<string, never>, AgWidgetDataFormat<unknown>> & { type: T };

export interface PayOpsRegistry extends AgRegistry {
  widgets: readonly (
    | AgDefaultWidgetDefinition
    | AgWidgetDefinition<"evidence-inspector", PanelState<"evidence-inspector">>
    | AgWidgetDefinition<"investigation-timeline", PanelState<"investigation-timeline">>
    | AgWidgetDefinition<"policy-decision", PanelState<"policy-decision">>
  )[];
}

export type PayOpsState = AgReportState<PayOpsRegistry>;
export type PayOpsData = AgDataSourcesDefinition<PayOpsRegistry>;

const AI_MODULES = [AgStudioAiModule];

const SIZE = { width: 12, height: 18 };
const MIN = { width: 6, height: 8 };

const widgets = createWidgets<PayOpsRegistry>({
  additionalTypes: [
    { id: "evidence-inspector", label: "Evidence Inspector", comp: EvidenceInspectorWidget, form: () => [], defaultSize: SIZE, minSize: MIN },
    { id: "investigation-timeline", label: "Investigation Timeline", comp: InvestigationTimelineWidget, form: () => [], defaultSize: SIZE, minSize: MIN },
    { id: "policy-decision", label: "Policy Decision", comp: PolicyDecisionWidget, form: () => [], defaultSize: SIZE, minSize: MIN },
  ],
  menu: [{ label: "PayOps", widgetIds: ["evidence-inspector", "investigation-timeline", "policy-decision"] }],
});

const theme = studioTheme.withParams(
  {
    accentColor: "#38bdf8",
    backgroundColor: "#0b1220",
    foregroundColor: "#e6ecf5",
    textColor: "#e6ecf5",
    borderColor: "#22314f",
    fontFamily: "var(--font-sans), system-ui, sans-serif",
    studioCanvasBackgroundColor: "#070b14",
    studioCanvasFontFamily: "var(--font-sans), system-ui, sans-serif",
  },
  "dark",
);

function loadSaved(key: string): PayOpsState | undefined {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as PayOpsState) : undefined;
  } catch {
    return undefined;
  }
}

interface Props {
  storageKey: string;
  label: string;
  data: PayOpsData;
  initialState: PayOpsState;
  height: number;
}

export default function StudioCanvas({ storageKey, label, data, initialState, height }: Props) {
  const config = useStudioConfig();
  const [mode, setMode] = useState<"view" | "edit">("view");
  // Bumping the key remounts Studio so a reset re-reads initialState.
  const [generation, setGeneration] = useState(0);
  const startState = useMemo(() => loadSaved(storageKey) ?? initialState, [storageKey, initialState, generation]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleStateUpdated = useCallback(
    (e: { state: unknown; durable: boolean }) => {
      if (!e.durable) return;
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(e.state));
      } catch {
        // Storage full or disabled: layout simply won't persist.
      }
    },
    [storageKey],
  );

  const resetLayout = () => {
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      // ignore
    }
    setGeneration((g) => g + 1);
  };

  return (
    <section aria-label={label} className="rounded-lg border border-line bg-ink-900">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <h2 className="text-sm font-semibold text-fg">{label}</h2>
        <span className="text-xs text-fg-faint">AG Studio · layout saved in this browser</span>
        <div className="ml-auto flex gap-2">
          {/* AG Studio mounts its AI assistant panel only in edit mode (view mode allows just `filters`). */}
          {config?.aiEnabled && mode === "view" && (
            <button type="button" className="btn btn-primary" onClick={() => setMode("edit")}>
              Ask AI about this incident
            </button>
          )}
          <button type="button" className="btn btn-ghost" aria-pressed={mode === "edit"} onClick={() => setMode((m) => (m === "view" ? "edit" : "view"))}>
            {mode === "view" ? "Edit layout" : "Done editing"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={resetLayout}>
            Reset layout
          </button>
        </div>
      </div>
      <div className="ag-theme-mode" data-ag-theme-mode="dark" style={{ height }}>
        {config && (
          <AgStudioProvider licenseKey={config.licenseKey} modules={config.aiEnabled ? AI_MODULES : undefined}>
            <AgStudio<PayOpsRegistry>
              key={generation}
              data={data}
              initialState={startState}
              widgets={widgets}
              theme={theme}
              mode={mode}
              onStateUpdated={handleStateUpdated}
              ai={config.aiEnabled ? payopsAi : undefined}
              style={{ height: "100%", width: "100%" }}
            />
          </AgStudioProvider>
        )}
      </div>
    </section>
  );
}
