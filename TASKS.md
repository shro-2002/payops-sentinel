# TASKS (live checklist — mirrors docs/task-graph.json)

## P0
- [x] G0 environment inspection
- [x] SPIKE PayPal sandbox: OAuth, card-funded order+capture, GET capture, partial refund, idempotent replay, over-refund 422
- [x] G1 schema + migrations + ADR-001
- [x] G2A PayPal client
- [x] G2B ledger ingest (idempotent, monotonic, reconciliation flags), detector, 8 synthetic scenarios
- [x] G4 AI investigator (Gemini function calling, 8-call budget, typed finding) + evidence checker + baseline
- [x] G5 policy engine + approval/execution state machine + AI drafting of proposals
- [x] Journeys A/B/C via API (live): investigation 10/10 claims; refund 1Y397979BV657782S verified; injection blocked
- [x] G2C AG Studio console
- [x] V1/V2 independent verification + fixes
- [~] G7 evaluation: 24 scenarios run; need fresh AI runs on frozen scenarios (quota-limited) + EVALUATION.md
- [ ] G6 UI journeys + Playwright
- [ ] README, demo script, storyboard, recording guide, Devpost text
- [ ] Dockerfiles, Makefile, .env.example, CI workflow, secret scan
- [ ] Release gate matrix

## P1
- [ ] AG Studio AI harness (defineAiTool → backend investigator)
- [ ] Webhook verification with registered webhook + tunnel
- [ ] More eval scenarios (36)

## Human gates pending (need explicit user approval)
- Publish repository · deploy · upload video · submit Devpost
