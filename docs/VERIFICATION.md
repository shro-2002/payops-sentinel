# Independent verification log

Verifiers ran in separate agent contexts, read-only, against the code and the running API. The integration owner
reconciled findings; an issue is "resolved" only when a regression test or reproduction now passes.

## V2 — security (2026-11-08)
Result: no CRITICAL/HIGH. No money-moving path broken (approval bypass, replay, race, swap, wrong target,
over-refund, synthetic target, forged webhook, SQL injection, SSRF all held).

| ID | Sev | Finding | Fix | Retest |
|---|---|---|---|---|
| V2-01 | MED | Unsigned webhook could store an event id first; the genuine signed event was then dropped as a duplicate | verified event now supersedes an UNVERIFIED row with the same id and is applied (`ingest_event`) | `test_unsigned_post_cannot_preclaim_a_real_event_id` PASS |
| V2-02 | MED | Malformed webhook bodies → HTTP 500 (bad `create_time`, long id, non-dict resource) | Pydantic `WebhookEventIn` shape check → 400; tolerant `_parse_ts` | `test_webhook_endpoint_rejects_malformed_events_with_400` PASS |
| V2-03 | MED | `async` webhook did blocking PayPal/DB I/O | work moved to `run_in_threadpool`; verify only attempted when transmission headers present | code review; webhook tests PASS |
| V2-04 | LOW | Malformed AI draft output (`Infinity`, `XXX`, dict target, non-dict) → 500 | drafter validates money fields, downgrades to MANUAL_REVIEW | `test_malformed_ai_draft_is_downgraded_to_manual_review` PASS |
| V2-05 | LOW | Lax money parsing (`1e3`, spaces, `_`, Arabic-Indic digits) | strict `[0-9]{1,9}(\.[0-9]{1,2})?` in `to_minor`; positive check; route regex uses `[0-9]` | `test_money_parsing_rejects_non_plain_amounts` (9 cases) PASS |
| V2-06 | LOW | Negative `limit`/`hours` → 500 | `Query(ge=, le=)` bounds | `test_query_params_are_bounded` PASS |
| V2-07 | LOW | Read endpoints are unauthenticated (PII-like demo fields, /docs) | documented; public deploy must gate reads / disable docs | open (deployment item) |
| P-2 | LOW | Execution stuck in CLAIMED after crash had no recovery | `/executions/{id}/verify` closes CLAIMED (provably never submitted) as FAILED | `test_claimed_but_unsubmitted_execution_can_be_closed_without_money` PASS |
| P-3 | LOW | Customer text could close `</untrusted>` tag in drafter prompt | `<`/`>` escaped before embedding | `test_drafter_escapes_untrusted_tag_breakout` PASS |
| P-4 | LOW | Sandbox lock was a substring check | exact host allowlist | `test_sandbox_lock_uses_exact_host` PASS |
| P-1 | LOW | `/verify` on a SUBMITTED execution replays the same refund later without re-checking expiry | accepted: replays only the originally approved request with the same idempotency key | open (documented) |

## Incident during verification (2026-11-08 11:17 IST)
A verifier's scratch script imported `app.db.session` before the test conftest set `DATABASE_URL`; the engine bound
to the default (main) DB and the session fixture's `drop_all` wiped the demo database. Root cause: the conftest
guarded the env var, not the engine. Fix: conftest and eval harness now assert `engine.url.database` before any
destructive operation (proven by reproducing the exact import order — guard raises). The demo world was rebuilt with
a fresh bootstrap at 11:35 IST; the first run's sandbox evidence (capture 1L082892HD997521E, refund
1Y397979BV657782S) is preserved in `reports/sandbox-bootstrap-2026-11-08-run1.json` and `docs/API_FEASIBILITY.md`,
and remains verifiable at PayPal.

## V1 — correctness
Pending (running).
