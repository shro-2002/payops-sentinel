# Evaluation

Harness: `backend/evals/run_eval.py` (frozen scenarios, rng seed 42, as_of 2026-11-07T18:00Z, dedicated
`payops_eval` DB). Results: `reports/evaluation-results.json`. Run date: 2026-11-08. Python 3.12.13.

## Current results (2026-11-08, after the prize-review audit)
Raw data: [`reports/evaluation-results-2026-11-08-claude-5scen.json`](../reports/evaluation-results-2026-11-08-claude-5scen.json)
(`python -m evals.run_eval --ai 5`, model `claude-opus-5-5`, tool budget 8). Changes since the earlier runs below:

- **Fair baseline.** It now scans all five dimensions (it used to skip `channel` and `product_category`) and prefers
  the finer slice on a near-tie (a SKU over its category, ≥ 90% of the share). Seed 42: 5/5 primary root cause.
  Over 20 seeds: partner_and_sku 13/20, single_partner 20/20, single_sku 18/20, region_outage 20/20,
  channel_bug 20/20 (91/100).
- **Answer key.** The partner_and_sku driver is the pair SwiftShip-EU × EU, so `region=EU` now counts as naming that
  cause (scored via `Scenario.equivalents`).
- **Cause claims.** A matching number no longer decides causality. Root causes need a structured cause claim that
  explains ≥ 25% of the excess refunds (`CAUSE_VERIFIED`); a ruled-out slice below 25% is `NOT_CAUSE_VERIFIED`; a
  claimed cause below 25% is `CONTRADICTED`; a ruled-out slice above 25% is `UNRESOLVED`. A share-only symmetric rule
  was tried first and rejected: within a dimension the shares sum to 1, so unrelated slices (e.g. channel=mobile at
  0.62 in the ParcelOne scenario) cleared it and the checker "contradicted" correct model judgements. A 10-seed probe
  found no single-slice threshold (share and rate lift) that separates causes from confounded slices.

| | Baseline (seed 42) | Claude, 5 scenarios |
|---|---|---|
| Primary root cause | 5/5 | 5/5 |
| Cause recall (mean) | 0.9 | 1.0 |
| Cause precision (mean) | — | 1.0 |
| Numeric claims matching source | — | 84/84 |
| Root-cause gate passed | 5/5 | 5/5 |
| Cause claims | 1 per scenario | 6 CAUSE_VERIFIED · 8 NOT_CAUSE_VERIFIED · 12 UNRESOLVED |
| Latency / cost | ~0.1 s / $0 | ~28.7 s / ~$0.13 per investigation |

Reading: on these planted, separable scenarios the fair baseline finds the primary cause too; the AI's measurable
edge is the second cause (recall 1.0 vs 0.9) and a checked explanation. The earlier "AI 5/5 vs baseline 3/5" came
from a handicapped baseline and the label issue above. Detection (P 1.0 / R 1.0) and safety (16/16, 0 unauthorized
executions) are unchanged. Journey C (S01) feeds the $500 injected proposal to `service.propose` directly to simulate
a compromised model; it does not test what a live model chooses.

The sections below are the earlier runs, kept for history.

## A. Detection (8 frozen synthetic scenarios)
| Scenario | Expected | Fired | Pass |
|---|---|---|---|
| partner_and_sku (multi-cause) | yes | yes | ✓ |
| single_partner | yes | yes | ✓ |
| single_sku | yes | yes | ✓ |
| region_outage | yes | yes | ✓ |
| channel_bug | yes | yes | ✓ |
| no_anomaly | no | no | ✓ |
| tiny_sample (12 captures, 3 refunds) | no | no | ✓ |
| high_but_stable (12% both windows) | no | no | ✓ |
Precision 1.0, recall 1.0 (TP 5, FP 0, FN 0). Caveat: scenarios are synthetic and designed by us.

## B. Root cause — deterministic baseline (fixed 4-query sequence)
Accuracy 3/5. Misses: `partner_and_sku` → picked `region=EU` (confounded with SwiftShip-EU; finds neither true cause);
`channel_bug` → never scans `channel`. Mean cause recall 0.6. 4 tool calls, ~15 ms, $0.

## C. Safety & reliability (16 cases, real policy/executor code, in-memory PayPal fake)
16/16 pass. Unauthorized actions executed: **0** (release-blocking metric). Policy violations blocked: 6
(prompt-injection proposal, over-refund, wrong target, refund without case, approval replay, post-approval tamper).
Also: PayPal outage, unknown-outcome reconciliation (same idempotency key, no duplicate), duplicate webhook,
unverified webhook, out-of-order events, invalid tool, invalid arguments (incl. SQL-injection string), fabricated
claims, LLM timeout, tool budget.

## D. Live AI (gemini-2.5-flash)
| Run | Result | Tool calls | Latency | Tokens in/out | Claims verified | Cause recall |
|---|---|---|---|---|---|---|
| 2026-11-08 #1 | FAILED (schema: numeric claim value) | 8 (+2 refused) | — | 10,909 / 4,809 | — | — |
| 2026-11-08 #2 | FAILED (schema: confidence "medium-high") | 8 (+9 refused) | — | 8,147 / 5,681 | — | — |
| 2026-11-08 #3 (typed response_schema) | COMPLETED | 8 (+1 refused) | 18.7 s | 6,740 / 3,616 | 10/10 | 2/2 |
| 2026-11-08 Claude (`claude-opus-5-5`, effort medium) | COMPLETED | 8 | 31.9 s | 14,018 / 3,252 | 18/18 | 2/2 |
Claude run: stored in the main DB (incident `caf026b1-…`); found SwiftShip-EU (primary), HDPH-200 (independent
secondary) and their overlap (50% refund rate). Est. cost ≈ $0.12 at $4/M in, $20/M out. Prose numbers not submitted as
claims ("93", "6.27") are flagged by the prose check, not counted as verified.
Run #3 transcript: `reports/live-ai-run-2026-11-08-run1.txt` (DB rows lost in the 11:17 incident).
Est. cost run #3 ≈ $0.011 at an assumed list price of $0.30/M in, $2.50/M out (verify current pricing).

### D2. Fresh Claude runs on the 5 frozen firing scenarios (2026-11-08, `--ai 5`, `claude-opus-5-5`, effort medium)
| Scenario | Truth | Claude found | Primary | Cause recall | Claims verified | Latency | Tokens in/out | Est. cost |
|---|---|---|---|---|---|---|---|---|
| partner_and_sku | SwiftShip-EU + HDPH-200 | both | ✓ | 2/2 | 14/14 | 24.8 s | 13,881 / 2,854 | $0.113 |
| single_partner | ParcelOne | ParcelOne | ✓ | 1/1 | 12/12 | 21.7 s | 13,830 / 2,514 | $0.106 |
| single_sku | CHRG-30W | CHRG-30W | ✓ | 1/1 | 13/13 | 24.2 s | 13,841 / 2,623 | $0.108 |
| region_outage | APAC | APAC (+ ParcelOne as secondary ✗) | ✓ | 1/1 | 14/14 | 23.3 s | 13,668 / 2,545 | $0.106 |
| channel_bug | marketplace | marketplace | ✓ | 1/1 | 17/17 | 23.4 s | 13,749 / 2,686 | $0.109 |

Claude: primary root cause 5/5, mean cause recall 1.0, claim faithfulness 70/70, 1 false-positive secondary cause,
8 tool calls every run, ~23 s, ~$0.11/run (list price $4/M in, $20/M out).
Baseline on the same 5: primary 3/5, mean cause recall 0.6 (misses multi-cause and channel), $0, ~15 ms.

### D3. Re-run after adding the read-only PayPal Agent Toolkit lookup (2026-11-08, same 5 scenarios, budget 8)
| Metric (mean over 5) | Before toolkit | With toolkit tool |
|---|---|---|
| Primary root cause | 5/5 | 5/5 |
| Cause recall | 1.0 | 1.0 |
| Claims verified | 70/70 | 58/58 |
| False-positive secondary causes | 1 (region_outage: ParcelOne) | 1 (same) |
| Latency | 23.5 s | 21.9 s |
| Tokens in / out | 13,794 / 2,644 | 14,462 / 2,450 |
| Est. cost per run | $0.108 | $0.107 |

No accuracy change. Input grew ~670 tokens/run (one more tool definition). The frozen scenarios are synthetic and
contain no PayPal objects, so `paypal_order_lookup` has nothing to check there; it is exercised on the real sandbox
captures of the demo world (live check 2026-11-08: wallet capture 9B331595R1964673U and refunded card capture
26N72420GP068431A both matched PayPal's record, including the $12.00 refund). Run-to-run variance at n=5 means the
latency/claim-count differences are not meaningful.

### The region_outage false positive (checked 2026-11-08)
Claude named ParcelOne as a secondary cause alongside APAC. Cross-tab of the frozen scenario's current window:

| Partner | APAC share of captures | APAC share of refunds | Refund rate outside APAC |
|---|---|---|---|
| ParcelOne | 12/22 (55%) | 7/7 (100%) | 0.0% |
| BlueDart-Intl | 17/26 (65%) | 5/5 (100%) | 0.0% |
| NorthPost | 10/23 (43%) | 4/4 (100%) | 0.0% |
| SwiftShip-EU | 9/19 (47%) | 3/3 (100%) | 0.0% |

Overall APAC share of captures: 53%. ParcelOne is **not** over-exposed to APAC (BlueDart-Intl is more so), and
outside APAC it has zero refunds. It ranked first on excess refunds by sampling chance (most APAC refunds, 7). So this
is a genuine false positive, not a confound the data forced: one `cross_slice(fulfillment_partner=ParcelOne, by=region)`
would have refuted it, but the model spent its 8-call budget on single-dimension rankings first. Possible fixes
(not yet applied, would need re-evaluation): require a cross-slice check before naming a secondary cause, or reserve
budget for it.

**Honest comparison:** on the multi-cause scenario the AI found both causes where the baseline found neither, but
n=1 completed Gemini run is not a statistically meaningful win (the Claude runs above are n=5 on frozen synthetic
scenarios we designed — still small, and synthetic); 2 of 3 runs failed closed on output format (fixed by a
typed schema). More AI runs are pending the LLM quota reset. AI costs ~1,000× the baseline's latency and money.
