"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo } from "react";

import { useApi } from "@/lib/api";
import { OVERVIEW_STATE, overviewData } from "@/lib/studio-reports";
import type { Capture, Incident, TrendPoint } from "@/lib/types";

import { EmptyState, ErrorState, Loading } from "./States";

const StudioCanvas = dynamic(() => import("./studio/StudioCanvas"), {
  ssr: false,
  loading: () => <Loading label="AG Studio dashboard" />,
});

const pct = (r: number) => `${(r * 100).toFixed(1)}%`;

function IncidentList() {
  const { data, error, loading, reload } = useApi<Incident[]>("incidents");
  if (error && !data) return <ErrorState error={error} onRetry={reload} what="incidents" />;
  if (loading && !data) return <Loading label="incidents" />;
  if (!data?.length) return <EmptyState text="No open incidents. The detector has not fired." />;
  return (
    <ul className="grid gap-3" aria-label="Open incidents">
      {data.map((i) => (
        <li key={i.id}>
          <Link
            href={`/incidents/${i.id}`}
            className="panel flex flex-wrap items-center gap-3 p-4 transition-colors hover:border-accent/60 focus-visible:border-accent"
            data-testid="incident-link"
          >
            <span className="badge badge-bad">{i.severity}</span>
            <span className="min-w-[min(100%,18rem)] flex-1">
              <span className="block font-semibold">{i.title}</span>
              <span className="block font-mono text-xs text-fg-faint">
                {i.detector} · {i.window_start} → {i.window_end}
              </span>
            </span>
            <span className="font-mono text-sm">
              <span className="text-bad">{pct(i.metrics.current.rate)}</span>
              <span className="text-fg-faint"> vs {pct(i.metrics.baseline.rate)} baseline</span>
            </span>
            <span className="badge badge-warn">{i.status}</span>
            <span className={i.root_cause_identified ? "badge badge-ok" : "badge badge-neutral"}>
              {i.root_cause_identified ? "AI driver confirmed by server" : "No confirmed AI driver yet"}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function OverviewDashboard() {
  const txns = useApi<Capture[]>("transactions?limit=2000");
  const trend = useApi<TrendPoint[]>("metrics/refund-trend?hours=192");
  const data = useMemo(() => (txns.data && trend.data ? overviewData(txns.data, trend.data) : null), [txns.data, trend.data]);
  const err = txns.error ?? trend.error;
  if (err && !data) return <ErrorState error={err} onRetry={() => (txns.reload(), trend.reload())} what="operations data" />;
  if (!data) return <Loading label="operations data" />;
  const live = txns.data?.filter((c) => c.origin !== "SYNTHETIC").length ?? 0;
  return (
    <>
      <p className="text-sm text-fg-muted">
        {txns.data?.length} captures loaded: <span className="badge badge-info">{live} sandbox live</span> real PayPal sandbox captures and{" "}
        <span className="badge badge-neutral">{(txns.data?.length ?? 0) - live} synthetic</span> labelled history rows.
      </p>
      <StudioCanvas storageKey="payops.studio.overview.v2" label="Operations overview" data={data} initialState={OVERVIEW_STATE} height={1150} />
    </>
  );
}

export function HomeConsole() {
  return (
    <div className="space-y-6">
      <section aria-labelledby="incidents-h" className="space-y-3">
        <h1 id="incidents-h" className="text-xl font-semibold tracking-tight">
          Open incidents
        </h1>
        <IncidentList />
      </section>
      <section aria-labelledby="overview-h" className="space-y-3">
        <h2 id="overview-h" className="text-lg font-semibold tracking-tight">
          Operations overview
        </h2>
        <OverviewDashboard />
      </section>
    </div>
  );
}
