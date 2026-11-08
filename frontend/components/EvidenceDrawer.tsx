"use client";

import { useEffect, useRef } from "react";

import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";

import { useApi } from "@/lib/api";
import type { Capture, Evidence, EvidenceRecords } from "@/lib/types";

import { gridTheme } from "./grid-setup";
import { ErrorState, Loading } from "./States";

const originCell = ({ data }: { data?: Capture }) =>
  data && data.origin !== "SYNTHETIC" ? (
    <span className="badge badge-info" title={`PayPal ID ${data.paypal_id ?? data.id}`}>PayPal sandbox</span>
  ) : (
    <span className="badge badge-neutral">synthetic</span>
  );

const COLS: ColDef<Capture>[] = [
  { field: "id", headerName: "Capture", cellClass: "font-mono", minWidth: 150 },
  { field: "origin", headerName: "Source", cellRenderer: originCell, minWidth: 130 },
  { field: "paypal_id", headerName: "PayPal ID", cellClass: "font-mono", minWidth: 150, valueFormatter: (p) => p.value ?? "—" },
  { field: "funding_source", headerName: "Funding", maxWidth: 110, valueFormatter: (p) => p.value ?? "—" },
  { field: "status" },
  { field: "amount", headerName: "Amount" },
  { field: "refunded", headerName: "Refunded" },
  { field: "currency", maxWidth: 90 },
  { field: "fulfillment_partner", headerName: "Partner" },
  { field: "product_sku", headerName: "SKU" },
  { field: "region", maxWidth: 90 },
  { field: "captured_at", headerName: "Captured at", minWidth: 190 },
];

export function EvidenceDrawer({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { data, error, loading, reload } = useApi<EvidenceRecords>(evidence ? `evidence/${evidence.id}/records` : null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (evidence && !d.open) d.showModal();
    if (!evidence && d.open) d.close();
  }, [evidence]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="evidence-title"
      className="m-0 ml-auto h-dvh max-h-none w-[min(100vw,880px)] max-w-none border-l border-line bg-ink-900 p-0 text-fg backdrop:bg-black/50"
      data-testid="evidence-drawer"
    >
      {evidence && (
        <div className="flex h-full flex-col">
          <div className="flex items-start gap-3 border-b border-line p-4">
            <div className="min-w-0 flex-1">
              <p className="panel-title">Claim drill-through · {evidence.query_id}</p>
              <h2 id="evidence-title" className="mt-1 text-base font-semibold leading-snug">
                {evidence.statement}
              </h2>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span className={evidence.verification === "VERIFIED" ? "badge badge-ok" : "badge badge-bad"}>{evidence.verification}</span>
                <span className="font-mono text-fg-muted">path {evidence.metric_path}</span>
                <span className="font-mono text-fg-muted">claimed {evidence.claimed_value}</span>
                <span className="font-mono text-fg-muted">stored {evidence.source_value ?? "—"}</span>
              </div>
              {evidence.reason && <p className="mt-1 text-xs text-bad">{evidence.reason}</p>}
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => ref.current?.close()}>
              Close
            </button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4">
            {loading && !data && <Loading label="evidence records" />}
            {error && <ErrorState error={error} onRetry={reload} what="evidence records" />}
            {data && (
              <>
                <section aria-labelledby="tool-result-h">
                  <h3 id="tool-result-h" className="panel-title">
                    Stored tool result ({data.query_id}) — the value the claim was checked against
                  </h3>
                  <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-line bg-ink-950 p-3 font-mono text-xs text-fg-muted" data-testid="tool-result-json">
                    {JSON.stringify(data.tool_result, null, 2)}
                  </pre>
                </section>
                <section aria-labelledby="records-h" className="flex min-h-[320px] flex-1 flex-col">
                  <h3 id="records-h" className="panel-title">
                    Ledger records{data.filter?.dimension ? ` where ${data.filter.dimension} = ${data.filter.value}` : " in the incident window (claim is window-level, no segment filter)"} · {data.records.length} rows
                  </h3>
                  <div className="mt-2 min-h-[300px] flex-1">
                    <AgGridReact<Capture>
                      theme={gridTheme}
                      rowData={data.records}
                      columnDefs={COLS}
                      defaultColDef={{ sortable: true, filter: true, resizable: true, flex: 1, minWidth: 100 }}
                      getRowId={(p) => p.data.id}
                    />
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      )}
    </dialog>
  );
}
