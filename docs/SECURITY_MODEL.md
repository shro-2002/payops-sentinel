# Security model

| Threat | Control | Test |
|---|---|---|
| AI moves money | investigator has 8 read-only tools; drafter can only *propose*; executor needs human approval | `test_investigator_has_no_write_tools`, eval S01 |
| Prompt injection in buyer memo / case text | text passed as quoted `untrusted_*` data; policy re-derives every fact from DB | Journey C live: model chose MANUAL_REVIEW; compromised $500 proposal rejected (4 checks) |
| Approval bypass | state machine; execute only from APPROVED | `test_unapproved_proposal_cannot_execute` |
| Approval swap/tamper | approval stores sha256(type,target,amount,currency,case); re-checked at execution | `test_amount_change_after_approval_invalidates`, S06 |
| Approval replay / race | single-use approval (consumed_at) + UNIQUE(proposal_id) and UNIQUE(approval_id) on executions + row lock | `test_parallel_execute_only_one_claims`, S05 |
| Wrong target / over-refund / synthetic target | policy: case↔capture match, remaining refundable, case request, $25 cap, origin must be a real provider capture | parametrized policy tests, S02–S04 |
| Stale state | fresh `GET capture` immediately before refund; policy re-run on provider status | `test_revalidation_catches_provider_side_full_refund` |
| Double refund on retry | stable `PayPal-Request-Id` per proposal; unknown outcome ⇒ UNVERIFIED, reconcile with same key | `test_unknown_outcome_stays_unverified...`, S08 |
| Forged webhook | `verify-webhook-signature` must return SUCCESS; otherwise stored as UNVERIFIED and ignored | `test_unverified_webhook_never_touches_ledger`, S10 |
| Duplicate / out-of-order events | UNIQUE provider ids + ON CONFLICT; monotonic status rank; conflicts flagged | S09, S11 |
| SQL injection | enums + regex-validated args, SQLAlchemy parameters, no model SQL | S13 |
| Fabricated numbers | claims verified against stored tool results scoped to the investigation | S14, `test_query_id_from_another_investigation_is_rejected` |
| Secret exposure | `.env` git-ignored; token only server-side; no secrets in responses/logs | V2 review, bundle grep (frontend) |
| Live money | client refuses non-sandbox hosts (exact allowlist) | `test_sandbox_lock_uses_exact_host` |
| Confused-deputy console proxy | proxy authenticates each operator with their own credential (`CONSOLE_OPERATORS`, scrypt hashes) BEFORE attaching the backend token, for reads and writes; with no operators configured it refuses everything unless `LOCAL_CONSOLE=1` (non-production opt-in). Never derived from the Host header | curl probes 2026-11-08 |
| CSRF / DNS rebinding | Host must be allowlisted (`CONSOLE_HOSTS`); writes need a same-origin Origin header and exactly `application/json` | curl probes: no Origin 403, cross-origin 403, foreign Host 403, text/plain 415 |
| Self-approval | approver identity comes from the authenticated proxy user, signed by the proxy (Ed25519) and verified by the backend with the public key only; proposer cannot approve (four-eyes) | `test_proposer_cannot_approve_own_action`, `test_operator_identity.py` |
| Replay racing / outliving approval | unknown-outcome replay only 60 s after claim and before approval TTL, only if fresh policy re-evaluation passes (else manual reconciliation, no submission) | `test_reconciliation_replay_refused_after_retention_window`, S08 |
| Customer data exposure | all data reads require the operator token (only `/config`, `/health`, `/ready`, webhook public) | `test_query_params_are_bounded` |

Known gaps (documented, not hidden): no rate limiting; per-operator Basic-auth credentials are a hackathon-grade
identity layer (use SSO/OIDC + MFA for production); webhook verification not exercised against a registered webhook; no tenant isolation.
This is a sandbox hackathon MVP — not a claim of production security or regulatory compliance.

## Four-eyes identity: shared-token header bypass (audit S1, fixed 2026-11-08)
**Finding (confirmed).** The backend took the operator name from the `X-Operator` header from any caller holding
the single `OPERATOR_TOKEN`. Anyone with that token (it lives in the server env) could propose as `alice` and approve
as `bob`: four-eyes was advisory against an insider. The browser path was never affected (the proxy derives the name
from the Basic-auth login), and the $25 cap and policy checks still applied.

**Fix.** `backend/app/api/identity.py`. The console proxy signs
`v1\n{operator}\n{METHOD}\n{path}\n{query}\n{sha256(body)}\n{unix_ts}\n{nonce}` with an Ed25519 private key
(`OPERATOR_IDENTITY_PRIVATE_KEY`, console server only) and sends `X-Operator`, `X-Operator-Ts`, `X-Operator-Nonce`,
`X-Operator-Sig`. The backend verifies with the public key (`OPERATOR_IDENTITY_PUBLIC_KEY`) over the exact bytes it
received and rejects missing, forged, re-targeted (other path, method, query or body), >60 s old or already-used
(nonce) signatures with 401 `OPERATOR_IDENTITY_INVALID`. The backend never holds the private key, so its env and
token cannot mint identities. Generate a pair with `node frontend/scripts/gen-identity-keys.mjs`.

**Without a key pair** the header is ignored and every caller is `operator:console`, so the proposer and approver are
always the same identity and self-approval is refused: missing config fails closed. The only exception is
`LOCAL_CONSOLE=1`, which accepts exactly `local-operator` and audits its self-approvals as
`FOUR_EYES_WAIVED_LOCAL_DEV`.

**Residual.** The nonce memory is per backend process (one worker in this deployment); several workers would need
a shared store. The backend's `LOCAL_CONSOLE` waiver has no environment guard of its own (audit S3): never set it on a deployed
backend.

