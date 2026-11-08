# BUILD STATUS (survives context resets — update at the end of every graph node)

Last update: 2026-11-08 11:50 IST · branch `feature/payops-sentinel` · last commit b740716 (not pushed)

## State of the world
- Postgres: `docker compose up -d db` (:5433). Demo DB rebuilt 11:37 IST: incident `caf026b1-…` "Refund rate 21.5%
  vs 3.4% baseline (20 refunds / 93 captures)"; live captures in `reports/sandbox-bootstrap.json`; cases RC-2041
  (legit $12) and RC-2042 (prompt injection). One BASELINE run; **no AI run yet in this DB**.
- API: preview `payops-api` :8100 · Web: preview `payops-web` :3100.
- Gemini free-tier quota exhausted for today's morning window (~17 requests used). Resets ~13:30 IST.

## Graph nodes
| Node | Status | Evidence |
|---|---|---|
| G0, SPIKE, G1, G2A, G2B, G4, G5 | done | 67 backend tests; API_FEASIBILITY #1–#10, #16 |
| G2C AG Studio console | done (read flows verified in browser; write flows built, not clicked end-to-end) | worker report: typecheck/lint/build pass, token-leak check pass, Playwright 2/2 |
| V2 security | done; MED/LOW fixed with regression tests | docs/VERIFICATION.md |
| V1 correctness | done; HIGH/MED fixed with regression tests (F12 documented) | docs/VERIFICATION.md |
| G6 integration | Journeys A/B/C passed via API (first DB); UI write-flow click-through pending | — |
| G7 evaluation | 24 scenarios; AI section needs fresh runs after quota reset | reports/evaluation-results.json |
| G8 docs/demo | README draft done; demo script/storyboard/recording/Devpost pending | — |

## Next executable tasks (in order)
1. After 13:30 IST: `python -m scripts.run_ai_once AI` on the demo incident (≈5 requests), then
   `python -m evals.run_eval --ai 2` if quota allows. Update EVALUATION.md with measured numbers.
2. UI Journey B click-through (draft or manual proposal → approve → execute) + Playwright spec for it.
3. Screenshot to `docs/img/incident-workspace.png`; demo script, storyboard, recording guide, Devpost text.
4. P1: AG Studio AI harness (`AgStudioAiModule`, `defineAiTool` → POST investigations) behind a flag.
5. Release gate matrix. Human gates: publish repo, deploy, upload video, submit.

## Known incidents
- 11:17 IST main DB wiped by a verifier script import-order bug; guard added (see VERIFICATION.md).

## Clean-clone test (2026-11-08 14:30 IST)
Fresh `git clone` of feature/payops-sentinel (03ca6cb) into scratch, followed only the README quickstart with PayPal
sandbox keys + OPERATOR_TOKEN + LOCAL_CONSOLE=1 + REPLAY_LLM=1 (no LLM key), DB on 5434 via PAYOPS_DB_PORT.
Results: pip install + alembic + bootstrap OK (3 real sandbox captures); API + web up; replayed Claude investigation
COMPLETED, 8 tool calls, 18/18 claims verified; manual proposal → self-approval (audited waiver) → execute → refund
7G505778A1970553N VERIFIED at PayPal (GET read-back). README fix found: manual-proposal button wording.
Clone DB volume and clone .env removed afterwards.
