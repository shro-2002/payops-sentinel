"use client";

import Link from "next/link";

import { useApi } from "@/lib/api";
import type { ConsoleConfig } from "@/lib/types";

export function ConsoleHeader() {
  const { data: cfg, error } = useApi<ConsoleConfig>("config");
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ink-900/95">
      <p className="border-b border-warn/40 bg-warn/10 px-4 py-1 text-center font-mono text-xs tracking-wide text-warn" role="note">
        SANDBOX · synthetic background data — no real money moves; history rows are generated, PayPal rows are sandbox objects
      </p>
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-3 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 rounded text-fg">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md border border-accent/50 bg-accent/10 font-mono text-xs font-bold text-accent">
            PS
          </span>
          <span className="text-base font-semibold tracking-tight">PayOps Sentinel</span>
        </Link>
        <span className="hidden text-sm text-fg-faint md:inline">Every financial claim the AI makes is backed by evidence you can inspect.</span>
        <div className="ml-auto flex flex-wrap items-center gap-2" aria-label="Environment status">
          {error && <span className="badge badge-bad">Backend unreachable</span>}
          {cfg && (
            <>
              <span className="badge badge-info">PayPal {cfg.paypal_env}</span>
              <span className={cfg.writes_enabled ? "badge badge-warn" : "badge badge-neutral"}>
                Writes {cfg.writes_enabled ? "enabled" : "disabled"}
              </span>
              <span className="badge badge-neutral">Refund cap {cfg.refund_cap}</span>
              <span className="badge badge-neutral">{cfg.llm_model}</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
