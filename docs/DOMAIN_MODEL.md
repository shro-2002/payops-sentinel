# Domain model

Money: `BIGINT` minor units + ISO currency; `origin` ∈ SANDBOX_LIVE | SYNTHETIC | WEBHOOK_VERIFIED | RECONCILED_GET.

- **PayPalEvent** raw provider event; UNIQUE provider_event_id; verification_status; processing_status.
- **Capture** provider_capture_id UNIQUE; amount/refunded (CHECK 0 ≤ refunded ≤ amount); status + status_rank
  (monotonic); analytic dimensions (sku, category, region, channel, fulfillment_partner); untrusted buyer_memo;
  reconciliation_flag.
- **Refund** provider_refund_id UNIQUE → Capture; reason_code.
- **LedgerEntry** append-only signed movement; UNIQUE(source_ref, entry_type).
- **Incident** detector output; UNIQUE(detector, window); metrics JSONB; states OPEN → ROOT_CAUSE_IDENTIFIED →
  RESOLVED. `root_cause_identified` ≠ corrective action done ≠ incident resolved.
- **InvestigationRun** AI|BASELINE, budget, tokens, latency, trace. **AgentToolCall** Qn per run, args, result.
- **Finding** typed conclusion. **EvidenceRecord** one claim: query_id, metric_path, claimed vs source value, verdict.
- **RemediationCase** concrete complaint on one capture (the only valid reason for a refund).
- **ActionProposal** typed action, details_hash, policy_result, idempotency_key.
- **ApprovalDecision** human decision bound to hash; expires; consumed once.
- **FinancialExecution** single-use claim (UNIQUE proposal, UNIQUE approval); request/response/verification payloads.
- **AuditEvent** append-only actor/event/details.

Action states: PROPOSED → POLICY_PASSED | POLICY_REJECTED → APPROVED | REJECTED → EXECUTING → EXECUTED |
EXECUTION_UNVERIFIED | EXECUTION_FAILED; APPROVAL_INVALID on expiry/tamper/reuse.
