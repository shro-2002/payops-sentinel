# BUILD STATUS (survives context resets — update at the end of every graph node)

Last update: 2026-11-08 17:30 IST · branch `feature/payops-sentinel` · publish copy `shro-2002/payops-sentinel`

## State of the world
- Postgres: `docker compose up -d db` (:5433). Demo world re-bootstrapped 17:20 IST: "Refund rate 21.5% vs 3.4%
  baseline (20 refunds / 93 captures)"; live captures in `reports/sandbox-bootstrap.json`; cases RC-2041 (legit $12)
  and RC-2042 (prompt injection).
- LLM: `claude-opus-5-5` (Anthropic). Judge mode `REPLAY_LLM=1` replays `backend/fixtures/replays/investigation.json`,
  recorded in a fresh (pre-refund) world so it re-verifies 18/18 there.
- Webhooks: registered and verified (signed `PAYMENT.CAPTURE.REFUNDED`, resend dedup; API_FEASIBILITY #11). They need
  a public URL (quick tunnel in the demo); GET read-back is the fallback.
- AG Studio: licensed key in `.env` (no watermark); AI module on, entry point **Ask AI about this incident**.

## Graph nodes
| Node | Status | Evidence |
|---|---|---|
| G0, SPIKE, G1, G2A, G2B, G4, G5 | done | backend pytest suite; API_FEASIBILITY #1–#11, #16 |
| G2C AG Studio console | done, incl. AI module and write flows clicked end-to-end | Playwright `smoke`, `studio-ai`, `sandbox-refund` |
| V1 correctness / V2 security | done; findings fixed with regression tests | docs/VERIFICATION.md |
| Prize-review audit (2026-11-08) | done: build fix, AI entry point, snapshot label, structured cause claims, fair baseline, signed operator identity, README truth pass | commits 2f345f8…4b75874; docs/SECURITY_MODEL.md; docs/EVALUATION.md "Current results" |
| G6 integration | Journeys A/B/C passed in the UI and via Playwright | `e2e/sandbox-refund.spec.ts` |
| G7 evaluation | 24 scenarios + 5 live Claude runs | reports/evaluation-results-2026-11-08-claude-5scen.json |
| G8 docs/demo | README, hero screenshot done; demo video, Devpost text pending | docs/img/ |

## Next executable tasks (in order)
1. Record the demo video (console flow + PayPal sandbox dashboard showing the same refund id).
2. Devpost text and AI-tools disclosure; tick AG Grid prize.
3. Technical freeze Nov 12, 12:00 IST; fresh-clone rehearsal of the README quickstart.

## Known incidents
- 11:17 IST main DB wiped by a verifier script import-order bug; guard added (see VERIFICATION.md).
- Judge replay fixture was first recorded after the demo refund landed in the window, so a fresh world re-verified
  only 9/18; re-recorded in a fresh world (17:25 IST).

## Clean-clone judge test (2026-11-08 17:20 IST)
Fresh `git clone` of the publish copy into scratch, README quickstart only: PayPal sandbox keys + OPERATOR_TOKEN +
`LOCAL_CONSOLE=1` + `REPLAY_LLM=1` (no LLM key, no identity keys), DB on 5434 via `PAYOPS_DB_PORT`. pip + alembic +
bootstrap OK; replayed Claude investigation 18 verified / 0 unsupported, ROOT_CAUSE_IDENTIFIED; manual proposal
RC-2041 → policy 16/16 → approve (audited `FOUR_EYES_WAIVED_LOCAL_DEV`) → execute → refund `1YX97456RS447463D`
**Verified at PayPal (GET read-back)**. RC-2042 at $500 blocked by 3 checks, no Approve button.
