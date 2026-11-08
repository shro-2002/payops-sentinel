"use client";

import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";

import type { AuditEvent } from "@/lib/types";

import { gridTheme } from "./grid-setup";

const COLS: ColDef<AuditEvent>[] = [
  { field: "id", headerName: "#", maxWidth: 70 },
  { field: "at", headerName: "At (UTC)", minWidth: 200 },
  { field: "actor", maxWidth: 140 },
  { field: "event", minWidth: 200, cellClass: "font-mono" },
  { field: "proposal_id", headerName: "Proposal", valueFormatter: (p) => (p.value ? String(p.value).slice(0, 8) : "—"), maxWidth: 120 },
  { headerName: "Details", valueGetter: (p) => JSON.stringify(p.data?.details ?? {}), flex: 3, tooltipValueGetter: (p) => p.value },
];

export function AuditGrid({ audit }: { audit: AuditEvent[] }) {
  return (
    <section aria-labelledby="audit-h" className="panel p-4">
      <h2 id="audit-h" className="panel-title">
        Audit history · {audit.length} events
      </h2>
      <div className="mt-3 h-[360px]">
        <AgGridReact<AuditEvent>
          theme={gridTheme}
          rowData={audit}
          columnDefs={COLS}
          defaultColDef={{ sortable: true, filter: true, resizable: true, flex: 1 }}
          getRowId={(p) => String(p.data.id)}
        />
      </div>
    </section>
  );
}
