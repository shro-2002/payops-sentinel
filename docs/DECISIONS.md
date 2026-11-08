# Decisions log

| Date | Decision | Why | Reversal trigger |
|---|---|---|---|
| 2026-11-08 | PostgreSQL relational ledger, no graph DB (ADR-001) | All queries ≤ 2 hops; SQL GROUP BYs | genuine multi-hop fraud-ring query |
| 2026-11-08 | Card-funded sandbox orders for demo captures | PayPal completes capture server-side; no simulated buyer approval; reproducible | judges need wallet flow → use payer-action link manually |
| 2026-11-08 | Gemini 2.5 Flash via google-genai, function calling with AFC disabled | key available; we must execute + log tools ourselves | quota exhaustion → add a second provider behind `ToolCallingLLM` |
| 2026-11-08 | Typed `response_schema` for the final finding | two free-form JSON runs failed schema (fail-closed) | — |
| 2026-11-08 | No LangGraph | a 6-turn bounded loop is ~60 lines; LangGraph adds deadline risk without state benefits | need durable resumable multi-agent state |
| 2026-11-08 | Refund requires an explicit RemediationCase | a refund-rate spike is never a refund reason; makes "legitimate reason" machine-checkable | — |
| 2026-11-08 | Approval bound to sha256(details); approval single-use, 15-min TTL; unique execution per proposal AND approval | prevents swap/replay/race | — |
| 2026-11-08 | Uncertain refund outcomes stay UNVERIFIED and reconcile with the SAME idempotency key | avoids double refunds | — |
| 2026-11-08 | Refund policy cap $25.00 per action | sandbox demo safety | config `REFUND_CAP_MINOR` |
| 2026-11-08 | ~~Webhook path built but marked NOT VERIFIED; GET reconciliation is the trust source~~ **Superseded same day:** webhook registered and verified end to end (API_FEASIBILITY #11); webhook-first verification, GET fallback (row below) | no registered webhook / public URL (at the time) | — |
| 2026-11-08 | ~~AG Studio 3.1.0 trial (watermark)~~ **Superseded same day:** licence key in `AG_STUDIO_LICENSE_KEY` (served by `/studio/config`), no watermark | no licence key at the time | key expiry (evaluation key, Dec 2026) |
| 2026-11-08 | Add Claude (`claude-opus-5-5`) as the default LLM provider behind `ToolCallingLLM`; Gemini kept as option | Gemini free-tier quota (~20 req/day) blocked evaluation; user supplied an Anthropic key. Manual tool loop retained (we validate/log every call); final finding via structured outputs; server-side refusal fallback on | quality/cost regressions vs Gemini on the eval |
| 2026-11-08 | Webhook-first verification: with `PAYPAL_WEBHOOK_ID` set, executions wait in SUBMITTED for PayPal's signed REFUNDED event; GET read-back stays the fallback | proves provider-pushed confirmation; signature verified via PayPal API | webhook outage → `/executions/{id}/verify` |
| 2026-11-08 | Incident metrics are a detection-time snapshot; investigation tools read the live ledger (same `refunded_at` window definition). The demo's real $12.00 refund `8FS10987XT445174H` (07:18:39 UTC, incident created 07:18:28) makes tools show 21 vs the snapshot's 20; UI labels the snapshot | an incident is a record of what fired; not a query bug | re-bootstrap before recording for identical numbers |
| 2026-11-08 | Root causes need a structured cause claim; rule: a cause explains >= 25% of excess refunds, checked asymmetrically (ruled-out material slice = UNRESOLVED) | a matching number "verified" false narratives; a symmetric share rule mislabelled confounded slices (shares sum to 1 per dimension) | a cross-slice test to settle UNRESOLVED |
| 2026-11-08 | Operator identity signed by the console proxy (Ed25519 over operator, method, path, query, body hash, ts, nonce); backend holds the public key only; no keys = identity `console` | shared OPERATOR_TOKEN let one person propose as alice and approve as bob | multi-worker backend needs a shared nonce store |
| 2026-11-08 | Judge replay fixture must be recorded in a freshly bootstrapped, pre-refund world | it is re-verified against the judge's fresh world; a refund in the window shifts the numbers | re-record after any change to bootstrap data |
