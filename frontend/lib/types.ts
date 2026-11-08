// Shapes returned by the PayOps backend (/api/v1). Money fields are decimal strings;
// the console displays them as-is and never does float math on them.

export interface WindowMetrics {
  captures: number;
  refunds: number;
  refunded_minor: number;
  rate: number;
}

export interface IncidentMetrics {
  current: WindowMetrics;
  baseline: WindowMetrics;
  checks: Record<string, boolean>;
  ratio: number;
  config: Record<string, number>;
  fired?: boolean;
}

export interface Incident {
  id: string;
  detector: string;
  severity: string;
  status: string;
  title: string;
  window_start: string;
  window_end: string;
  metrics: IncidentMetrics;
  root_cause_identified: boolean;
  created_at?: string;
}

export interface ToolCall {
  id: string;
  query_id: string;
  seq: number;
  tool: string;
  arguments: Record<string, unknown>;
  status: "OK" | "REJECTED";
  error: string | null;
  duration_ms: number;
  result: unknown;
}

export interface Evidence {
  id: string;
  query_id: string;
  tool_call_id: string;
  statement: string;
  metric_path: string;
  claimed_value: string;
  source_value: string | null;
  verification: "VERIFIED" | "UNSUPPORTED" | "CAUSE_VERIFIED" | "NOT_CAUSE_VERIFIED" | "CONTRADICTED" | "UNRESOLVED";
  reason: string | null;
}

export interface Finding {
  id: string;
  hypothesis: string;
  observed_anomaly: string;
  explanation: string;
  uncertainty: string;
  confidence: string;
  root_cause: { dimension: string; value: string } | null;
  recommended_action: string;
  verified_claims: number;
  unsupported_claims: number;
  evidence: Evidence[];
}

export interface Investigation {
  id: string;
  mode: "AI" | "BASELINE" | "REPLAY";
  model: string | null;
  status: string;
  tool_calls_used: number;
  max_tool_calls: number;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string | null;
  created_at?: string;
  trace: unknown[];
  tool_calls: ToolCall[];
  finding: Finding | null;
}

export interface PolicyCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Execution {
  id: string;
  status: string;
  provider_refund_id: string | null;
  provider_status: string | null;
  error: string | null;
  verified_at: string | null;
  verified_at_paypal?: boolean;
  verified_via?: "paypal_webhook" | "paypal_get" | null;
}

export interface Approval {
  approve?: boolean;
  approved?: boolean;
  actor?: string;
  note?: string | null;
  at?: string;
  details_hash?: string;
}

export interface Proposal {
  id: string;
  action_type: "NO_ACTION" | "MANUAL_REVIEW" | "PARTIAL_REFUND";
  status: string;
  target_capture_id: string | null;
  amount: string | null;
  currency: string | null;
  case_ref: string | null;
  reason: string;
  proposed_by: "AI" | "OPERATOR";
  details_hash: string;
  policy: { passed: boolean; checks: PolicyCheck[] } | null;
  approvals: Approval[];
  execution: Execution | null;
  created_at?: string;
}

export interface RemediationCase {
  case_ref: string;
  capture_id: string;
  issue_type: string;
  requested: string;
  currency: string;
  customer_statement_untrusted: string;
  status: string;
}

export interface AuditEvent {
  id: number;
  at: string;
  actor: string;
  event: string;
  proposal_id: string | null;
  details: Record<string, unknown>;
}

export interface IncidentDetail extends Incident {
  investigations: Investigation[];
  proposals: Proposal[];
  remediation_cases: RemediationCase[];
  audit: AuditEvent[];
}

export interface Capture {
  id: string;
  order_id: string | null;
  amount: string;
  refunded: string;
  currency: string;
  status: string;
  captured_at: string;
  product_sku: string;
  product_category: string;
  region: string;
  channel: string;
  fulfillment_partner: string;
  customer_ref: string;
  origin: "SANDBOX_LIVE" | "SYNTHETIC" | "WEBHOOK_VERIFIED" | "RECONCILED_GET";
  verification_status: string;
  reconciliation_flag: string | null;
  buyer_memo_untrusted: string | null;
  source_label?: "PayPal sandbox" | "synthetic";
  paypal_id?: string | null;
  funding_source?: string | null;
}

export interface TrendPoint {
  hour: string;
  captures: number;
  refunds: number;
}

export interface EvidenceRecords {
  evidence_id: string;
  query_id: string;
  filter: { dimension: string | null; value: string | null } | null;
  tool_result: unknown;
  records: Capture[];
}

export interface ConsoleConfig {
  writes_enabled: boolean;
  refund_cap: string;
  llm_model: string;
  max_tool_calls: number;
  paypal_env: string;
  webhook_verification: string;
}
