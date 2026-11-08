.PHONY: db migrate test eval bootstrap api web e2e secrets wallet clean-clone-check
db:        ; docker compose up -d db
migrate:   ; cd backend && .venv/bin/alembic upgrade head
test:      ; cd backend && .venv/bin/pytest
eval:      ; cd backend && .venv/bin/python -m evals.run_eval
bootstrap: ; cd backend && .venv/bin/python -m scripts.bootstrap_demo --reset   # creates REAL sandbox captures
api:       ; cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
web:       ; cd frontend && npm run dev -- --hostname 127.0.0.1 --port 3100
e2e:       ; cd frontend && npm run test:e2e
secrets:   ; docker run --rm -v "$$PWD:/repo" zricethezav/gitleaks:v8.21.2 detect --source /repo --no-git -v --redact
wallet:    ; cd backend && .venv/bin/python -m scripts.seed_wallet_captures --count 2   # needs SANDBOX_BUYER_EMAIL/PASSWORD in .env
clean-clone-check: ; scripts/clean-clone-check.sh . HEAD   # typecheck + next build on a fresh clone (CI frontend job)
