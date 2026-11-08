# PayOps Sentinel — agent context

Payment incidents, investigated with receipts. PayPal AI Hackathon 2026 (deadline 2026-11-13 01:30 IST; internal
target 2026-11-12 21:00 IST). Primary prize target: Best Use of AG Grid (AG Studio).

## Resume protocol (every new session)
Read `CLAUDE.md`, `TASKS.md`, `docs/BUILD_STATUS.md`, `docs/DECISIONS.md`, `docs/task-graph.json`. Resume the
first non-done task. Never regenerate the app.

## Layout
- `backend/` FastAPI + SQLAlchemy + Alembic (Python 3.12 venv at `backend/.venv`).
  `app/integrations/paypal` client · `app/ledger` ingest + synthetic scenarios · `app/detection` refund-rate
  detector · `app/investigator` read-only tools, evidence checker, AI + baseline loops · `app/policy` deterministic
  checks · `app/actions` approval/execution state machine + AI drafting · `app/api` routes.
- `frontend/` Next.js + AG Studio console (node_modules is a symlink to `node_modules.nosync` — iCloud).
- `docs/` specs, ADRs, task graph, evaluation. `reports/` generated evidence.

## Commands
- DB: `docker compose up -d db` (Postgres 16 on :5433; dbs payops, payops_test, payops_eval)
- Migrate: `cd backend && .venv/bin/alembic upgrade head`
- Tests: `cd backend && .venv/bin/pytest` (unit/integration; live tests opt-in `-m live`)
- Demo world (creates REAL sandbox captures): `cd backend && .venv/bin/python -m scripts.bootstrap_demo --reset`
- Eval: `cd backend && .venv/bin/python -m evals.run_eval` (`--ai N` spends LLM quota)
- API: preview config `payops-api` (:8100) — Desktop TCC blocks exec of venv binaries from the preview runner,
  so it launches via `python3.12 -c` with the venv site-packages on sys.path.

## Hard rules
- Money = integer minor units; strings at the PayPal boundary. Sandbox only (client refuses non-sandbox URLs).
- The investigator gets read-only tools only; never give it write access or raw SQL.
- Every refund needs: open remediation case on the same capture, policy pass, human approval bound to the
  details hash, single-use execution claim, fresh provider GET re-validation, GET verification after submit.
- Unverified webhooks are stored, never applied. Never mark money states by hand to make a demo look good.
- Gemini free tier ≈ 20 requests/day/model; an investigation uses 4–6. Don't burn quota on probes.
- Never commit `.env*`.
