# API Feasibility — evidence log

VERIFIED = exercised successfully **in this project environment** (sandbox), with the date and the observed result.
Credentials were never printed; ids below are sandbox ids.

| # | Dependency / feature | Source | Endpoint / method | Auth | Sandbox | Test performed (2026-11-08) | Actual result | Status | Fallback |
|---|---|---|---|---|---|---|---|---|---|
| 1 | PayPal OAuth2 | developer.paypal.com REST auth | `POST /v1/oauth2/token` (client_credentials) | Basic client id/secret | yes | token request | 200, `expires_in=32400`, scopes include refund + payouts | **VERIFIED** | — |
| 2 | Orders v2 create (card source) | Orders v2 API ref | `POST /v2/checkout/orders` + `payment_source.card` (PayPal published sandbox test card) + `PayPal-Request-Id` | Bearer | yes | $12.00 USD order | 201 `COMPLETED`, capture `22U625783L592623H` returned inline — no buyer redirect needed, nothing simulated | **VERIFIED** | wallet flow (#3) |
| 3 | Orders v2 create (PayPal wallet) | Orders v2 API ref | same, `payment_source.paypal.experience_context` | Bearer | yes | $9.00 order | 200 `PAYER_ACTION_REQUIRED`, `payer-action` link present. Buyer login not automated (by design) | VERIFIED (create only) | card source (#2) is used for reproducible demos |
| 4 | Capture order | Orders v2 | `POST /v2/checkout/orders/{id}/capture` | Bearer | yes | not needed for card source (auto-captured) | — | implemented, not exercised | — |
| 5 | Get capture | Payments v2 | `GET /v2/payments/captures/{id}` | Bearer | yes | GET after capture and after refund | 200 `COMPLETED` → `PARTIALLY_REFUNDED`; `custom_id` round-trips | **VERIFIED** | — |
| 6 | Refund capture (partial) | Payments v2 | `POST /v2/payments/captures/{id}/refund` + `PayPal-Request-Id` | Bearer | yes | $2.50 partial refund | 201 `COMPLETED`, refund `4K142329BU036764L` | **VERIFIED** | — |
| 7 | Refund idempotency | PayPal idempotency docs | same request, same `PayPal-Request-Id` | Bearer | yes | replayed identical request | 200 with the **same** refund id — no duplicate | **VERIFIED** | — |
| 8 | Over-refund protection (provider side) | Payments v2 errors | refund > remaining | Bearer | yes | $50 on $12 capture | 422 `REFUND_AMOUNT_EXCEEDED` | **VERIFIED** | our policy blocks earlier |
| 9 | Get refund | Payments v2 | `GET /v2/payments/refunds/{id}` | Bearer | yes | GET | 200 `COMPLETED`, amount matches | **VERIFIED** | — |
| 10 | Journey B end-to-end via app | — | app `POST /proposals/{id}/execute` | operator token | yes | AI-drafted $12.00 refund on capture `1L082892HD997521E` (case RC-2041), human-approved | refund `1Y397979BV657782S` COMPLETED, verified by GET, ledger updated | **VERIFIED** | — |
| 11 | Webhooks: register + signature verification + dedup | Webhooks API | `POST /v1/notifications/webhooks`, `POST /v1/notifications/verify-webhook-signature`, `POST /v1/notifications/webhooks-events/{id}/resend` | Bearer | yes | cloudflared quick tunnel → API; registered webhook `6KW38712WB740873H` (COMPLETED/REFUNDED, `scripts/register_webhook.py`); real app refund `8FS10987XT445174H` ($12.00, case RC-2041, proposed by alice, approved by bob) | event `WH-6D158839BM755770A-6U06612621241293H` (PAYMENT.CAPTURE.REFUNDED) arrived ~20 s after submit; verify-webhook-signature → SUCCESS; action SUBMITTED → **VERIFIED via `paypal_webhook`**; PayPal resend (HTTP 202, empty body; a body with `webhook_ids` returned 404) redelivered it → recorded `DUPLICATE_PROVIDER_EVENT`, still exactly 1 refund row; capture `7B335909WT979644L` refunded_minor 1200 | **VERIFIED** (2026-11-08) | GET read-back (`/executions/{id}/verify`) when no webhook is configured or the event never arrives. Quick-tunnel hostnames change on restart → re-run `register_webhook.py` |
| 12 | Payouts | Payouts API | — | — | — | not attempted (P1, cut) | — | NOT USED | — |
| 13 | AED currency | — | — | — | — | not attempted; all transactions USD | — | NOT USED | — |
| 14 | AG Studio 3.1.0 (`ag-studio`, `ag-studio-react`) | npm tarball `.d.ts` + ag-grid.com/studio docs | `AgStudio`, `AgStudioProvider`, `createWidgets`, `studioTheme`, `onStateUpdated` | trial (no key → watermark, all features) | n/a | type inspection 2026-11-08; integration in `frontend/` | see `docs/BUILD_STATUS.md` G2C evidence | see BUILD_STATUS | plain AG Grid |
| 15 | AG Studio AI module | `AgStudioAiModule`, `createAiHarness`, `api.defineAiTool`, host `AgLlmAdapter` | — | STUDIO-PRO-AI (trial unlocks) | n/a | API confirmed in types | — | P1 | — |
| 16 | Gemini 2.5 Flash function calling (`google-genai` 1.16.1) | ai.google.dev | `models.generate_content` with `FunctionDeclaration`s, AFC disabled, `response_schema` | API key | n/a | 3 live investigations | run 1+2: schema-invalid final JSON (fail-closed); run 3 (typed `response_schema`): COMPLETED, 8 tool calls, 10/10 claims verified | **VERIFIED** | deterministic baseline investigator |

## Notes
- Card-funded sandbox orders complete server-side using PayPal's published sandbox test card. This is PayPal's own
  processing, not a simulated approval. The wallet (buyer-login) flow is implemented but not automated.
- Gemini free tier allows ~20 requests/day/model. One investigation uses 4–6 requests (parallel tool calls per turn).
