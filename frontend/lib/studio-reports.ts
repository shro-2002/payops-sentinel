import type { PayOpsData, PayOpsState } from "@/components/studio/StudioCanvas";

import type { Capture, Investigation, TrendPoint } from "./types";

type Agg = "sum" | "avg" | "count" | "countd";
const f = (id: string, aggregation?: Agg) => (aggregation ? { id, aggregation } : { id });
const title = (text: string) => ({ title: { enabled: true, text } });

// Rows fed to Studio. Money stays a display string; is_refund is a 0/1 flag derived
// by string comparison so refund rate = avg(is_refund) without float math on amounts.
function captureRows(captures: Capture[]) {
  return captures.map((c) => ({
    id: c.id,
    origin: c.source_label === "PayPal sandbox" || c.origin !== "SYNTHETIC" ? "PayPal sandbox" : "synthetic",
    paypal_id: c.paypal_id ?? "— (generated)",
    funding_source: c.funding_source ?? (c.origin === "SYNTHETIC" ? "—" : "unknown"),
    status: c.status,
    amount: `${c.amount} ${c.currency}`,
    refunded: `${c.refunded} ${c.currency}`,
    is_refund: c.refunded !== "0.00" ? 1 : 0,
    refund_rate: c.refunded !== "0.00" ? 1 : 0,
    captured_at: new Date(c.captured_at),
    product_sku: c.product_sku,
    product_category: c.product_category,
    region: c.region,
    channel: c.channel,
    fulfillment_partner: c.fulfillment_partner,
    verification_status: c.verification_status,
  }));
}

const CAPTURE_FIELDS = [
  { id: "id", name: "Capture ID", format: "textFormat" },
  { id: "origin", name: "Source", format: "textFormat" },
  { id: "paypal_id", name: "PayPal ID", format: "textFormat" },
  { id: "funding_source", name: "Funding", format: "textFormat" },
  { id: "status", name: "Status", format: "textFormat" },
  { id: "amount", name: "Amount", format: "textFormat" },
  { id: "refunded", name: "Refunded", format: "textFormat" },
  { id: "is_refund", name: "Refunds", format: "integerFormat" },
  { id: "refund_rate", name: "Refund rate", format: "percentageFormat" },
  { id: "captured_at", name: "Captured at", format: "dateTimeFormat" },
  { id: "product_sku", name: "SKU", format: "textFormat" },
  { id: "product_category", name: "Category", format: "textFormat" },
  { id: "region", name: "Region", format: "textFormat" },
  { id: "channel", name: "Channel", format: "textFormat" },
  { id: "fulfillment_partner", name: "Fulfillment partner", format: "textFormat" },
  { id: "verification_status", name: "Verification", format: "textFormat" },
] as const;

const GRID_COLS = ["origin", "paypal_id", "funding_source", "id", "captured_at", "status", "amount", "refunded", "fulfillment_partner", "product_sku", "region", "verification_status"].map(
  (c) => f(`captures.${c}`),
);

export function overviewData(captures: Capture[], trend: TrendPoint[]): PayOpsData {
  return {
    sources: [
      { id: "captures", name: "Captures", data: captureRows(captures), fields: [...CAPTURE_FIELDS] },
      {
        id: "trend",
        name: "Hourly refund trend",
        data: trend.map((t) => ({ hour: new Date(t.hour), captures: t.captures, refunds: t.refunds })),
        fields: [
          { id: "hour", name: "Hour", format: "dateTimeFormat" },
          { id: "captures", name: "Captures", format: "integerFormat" },
          { id: "refunds", name: "Refunds", format: "integerFormat" },
        ],
      },
    ],
  };
}

export const OVERVIEW_STATE: PayOpsState = {
  selectedPageId: "overview",
  pages: [
    {
      id: "overview",
      widgets: {
        kpiCaptures: { type: "value", dataMapping: { value: [f("captures.id", "count")] }, format: title("Captures (all origins)") },
        kpiRefunds: { type: "value", dataMapping: { value: [f("captures.is_refund", "sum")] }, format: title("Refunded captures") },
        kpiRate: { type: "value", dataMapping: { value: [f("captures.refund_rate", "avg")] }, format: title("Refund rate (share of captures)") },
        origin: {
          type: "donut-chart",
          dataMapping: { categoryKey: [f("captures.origin")], valueKey: [f("captures.id", "count")] },
          format: title("Captures by origin"),
        },
        trend: {
          type: "line-chart",
          dataMapping: { categoryKey: [f("trend.hour")], valueKey: [f("trend.refunds", "sum"), f("trend.captures", "sum")] },
          format: title("Hourly captures vs refunds (8 days)"),
        },
        partner: {
          type: "column-chart-grouped",
          dataMapping: { categoryKey: [f("captures.fulfillment_partner")], valueKey: [f("captures.is_refund", "sum")] },
          format: title("Refunds by fulfillment partner"),
        },
        sku: {
          type: "bar-chart-grouped",
          dataMapping: { categoryKey: [f("captures.product_sku")], valueKey: [f("captures.is_refund", "sum")] },
          format: title("Refunds by product SKU"),
        },
        grid: { type: "grid", dataMapping: { cols: GRID_COLS }, format: title("Captures ledger — Source: PayPal sandbox (with PayPal ID) vs synthetic (generated)") },
      },
      widgetLayout: {
        kpiCaptures: { xTrack: 0, yTrack: 0, xSpan: 6, ySpan: 7 },
        kpiRefunds: { xTrack: 6, yTrack: 0, xSpan: 6, ySpan: 7 },
        kpiRate: { xTrack: 12, yTrack: 0, xSpan: 6, ySpan: 7 },
        origin: { xTrack: 18, yTrack: 0, xSpan: 6, ySpan: 15 },
        trend: { xTrack: 0, yTrack: 7, xSpan: 18, ySpan: 16 },
        partner: { xTrack: 0, yTrack: 23, xSpan: 12, ySpan: 16 },
        sku: { xTrack: 12, yTrack: 23, xSpan: 12, ySpan: 16 },
        grid: { xTrack: 0, yTrack: 39, xSpan: 24, ySpan: 26 },
      },
    },
  ],
};

interface ContributorRow {
  current_rate?: number;
  share_of_excess?: number;
  excess_refunds?: number;
  current_refunds?: number;
}

// Flattens every top_contributors tool result of the investigation into one table.
function contributorRows(inv: Investigation | null) {
  if (!inv) return [];
  return inv.tool_calls
    .filter((c) => c.tool === "top_contributors" && c.status === "OK" && c.result)
    .flatMap((c) => {
      const r = c.result as { dimension?: string; by_value?: Record<string, ContributorRow> };
      return Object.entries(r.by_value ?? {}).map(([value, v]) => ({
        query: c.query_id,
        dimension: r.dimension ?? "",
        segment: `${r.dimension}=${value}`,
        share_of_excess: v.share_of_excess ?? 0,
        current_rate: v.current_rate ?? 0,
        current_refunds: v.current_refunds ?? 0,
      }));
    });
}

export function investigationData(captures: Capture[], windowStart: string, windowEnd: string, inv: Investigation | null): PayOpsData {
  const start = Date.parse(windowStart);
  const end = Date.parse(windowEnd);
  const inWindow = captures.filter((c) => {
    const t = Date.parse(c.captured_at);
    return t >= start && t <= end;
  });
  return {
    sources: [
      { id: "captures", name: "Captures in incident window", data: captureRows(inWindow), fields: [...CAPTURE_FIELDS] },
      {
        id: "contributors",
        name: "Top contributors (stored tool results)",
        data: contributorRows(inv),
        fields: [
          { id: "query", name: "Query", format: "textFormat" },
          { id: "dimension", name: "Dimension", format: "textFormat" },
          { id: "segment", name: "Segment", format: "textFormat" },
          { id: "share_of_excess", name: "Share of excess refunds", format: "percentageFormat" },
          { id: "current_rate", name: "Current refund rate", format: "percentageFormat" },
          { id: "current_refunds", name: "Current refunds", format: "integerFormat" },
        ],
      },
    ],
  };
}

export const INVESTIGATION_STATE: PayOpsState = {
  selectedPageId: "investigation",
  pages: [
    {
      id: "investigation",
      widgets: {
        evidence: { type: "evidence-inspector", dataMapping: {}, format: title("Evidence Inspector") },
        timeline: { type: "investigation-timeline", dataMapping: {}, format: title("Investigation Timeline") },
        rootCause: {
          type: "bar-chart-grouped",
          dataMapping: { categoryKey: [f("contributors.segment")], valueKey: [f("contributors.share_of_excess", "sum")] },
          format: title("Root-cause breakdown: share of excess refunds by segment"),
        },
        policy: { type: "policy-decision", dataMapping: {}, format: title("Policy Decision") },
        windowGrid: { type: "grid", dataMapping: { cols: GRID_COLS }, format: title("Captures in incident window") },
      },
      widgetLayout: {
        evidence: { xTrack: 0, yTrack: 0, xSpan: 14, ySpan: 24 },
        timeline: { xTrack: 14, yTrack: 0, xSpan: 10, ySpan: 24 },
        rootCause: { xTrack: 0, yTrack: 24, xSpan: 14, ySpan: 22 },
        policy: { xTrack: 14, yTrack: 24, xSpan: 10, ySpan: 22 },
        windowGrid: { xTrack: 0, yTrack: 46, xSpan: 24, ySpan: 24 },
      },
    },
  ],
};
