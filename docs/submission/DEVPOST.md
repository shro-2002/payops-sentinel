# Devpost submission text: PayOps Sentinel

**Tagline:** Evidence-first AI that tries to disprove its own payment-incident explanations before anyone touches
money.

## Inspiration
When a merchant's refund rate jumps, ops teams guess. They blame the channel with the most refunds, refund
everyone who complains, and move on. The obvious explanation is often a decoy. A segment can look guilty because it is
big, or because it happens to overlap the real problem. Acting on the wrong explanation costs money twice: the
wrong fix, and the real problem left running.

## What it does
PayOps Sentinel is an AI financial incident commander for payment operations:
**Detect → Investigate → Challenge → Quantify → Recommend → Authorize → Verify.**

- **Detects** a refund-rate spike with a deterministic detector.
- **Investigates** with Claude: read-only, argument-validated tools across partner, SKU, category, region and
  channel. The AI must write down competing hypotheses, including the ones a confounder could explain.
- **Challenges** every hypothesis with a deterministic falsification engine:
  - a sample-size floor;
  - an exact test of the refund-rate lift vs the rest of the window and vs the slice's own baseline, corrected for
    multiple testing;
  - a stratified test (Mantel-Haenszel) of whether the lift survives inside every other dimension;
  - aliasing checks;
  - a conditional re-test so a second independent driver isn't hidden by the first.

  Outcomes: *association supported*, *contradicted* (with what explains it), *unresolved* (abstain) or *insufficient
  evidence*. **The server re-runs this test on every driver the AI names.** The AI cannot mark its own story verified.
- **Quantifies** the affected cohort per supported driver: transactions, customers, captured value, refunded,
  remaining refundable, and open cases. Everything is in integer minor units per currency, and every figure is
  labelled *actual PayPal data*, *synthetic history* or *scenario estimate*. Captured value is never called a loss.
- **Recommends** typed operational actions (carrier investigation, quality review or inventory hold, customer
  outreach), honestly marked as manual follow-ups. If nothing survives, it escalates instead.
- **Authorizes and verifies** individual customer refunds through PayPal. The AI only drafts. 16 deterministic policy
  checks run, then a second operator's Ed25519-signed approval bound to the action's hash, a single-use execution
  claim, a fresh PayPal read, an idempotent refund, and PayPal verification.
- Keeps **investigation, operational response and PayPal execution** as separate statuses. A refund settles a
  customer's case; it never "resolves" the incident.

In the demo, refunds jump from 3.6% to 26.8%. The mobile channel holds the largest share of excess refunds, and both
a share-based rule and our own earlier version blamed it. PayOps Sentinel contradicts mobile: 70% of mobile orders
ship via NorthPost, against 46% overall. It supports two suspected contributing factors, the NorthPost carrier and a
defective HDPH-200 headphone batch, and sizes both cohorts. Then it refunds one real customer with a defective
headphone through the human-approved PayPal flow, and blocks a second case whose customer text is a prompt injection.

## Who it's for
Payment-operations analysts and risk teams at merchants and marketplaces that run on PayPal, who need to explain and
contain refund incidents fast, without trusting an LLM with money or with unchecked causal claims.

## Why AI, and why not only AI
A fixed SQL baseline finds the obvious driver about as often as anything else. What the AI adds:
- it decides which rival explanations to test next;
- it reads reason codes;
- it explains the incident in plain language with every number cited to a stored query result (114/118 claims
  matched their source across our live adversarial runs).

What the AI must not do is decide causality or move money. So both are deterministic: the falsification engine
judges the explanation, and policy, human approval and PayPal verification govern the money.

## Why PayPal
PayPal is where the money and the ground truth live:
- real sandbox captures are the refund targets;
- refunds go through PayPal's capture-refund API with idempotency keys;
- every refund is re-validated before and verified after by reading PayPal back, or through verified webhooks;
- the investigator can cross-check a ledger row against PayPal's own order record through the **PayPal Agent
  Toolkit, read-only** (`orders.get` only, enforced three ways).

## How we built it
- **Backend:** FastAPI, SQLAlchemy and PostgreSQL. An idempotent ledger with integer minor units and an append-only
  audit log.
- **AI:** Claude (`claude-opus-5-5`) through a manual tool loop (we execute, validate and log every call), with
  structured outputs. Gemini is optional. Judge mode replays a recorded Claude run, labelled REPLAY.
- **Frontend:** Next.js and **AG Studio**, with dashboards, three custom widgets, and the AG Studio AI module. Its
  system prompt is owned by the server and it has server-side request and token budgets.
- **Methodology:** a dependency-aware task graph, a single investigator agent with structured tools, and independent
  review agents (a separate-context adversarial code review changed our statistics before we froze the results).

## Measured results
Committed in `reports/hypothesis-eval-results.json`. These are synthetic scenarios we wrote. 7 adversarial incidents
are built to fool an investigator, plus 5 classic ones. Thresholds were calibrated on seeds 1–10; seeds 11–40 are
held out, 360 runs per system:

| Held out | Share baseline (prior best) | Falsification engine |
|---|---|---|
| Wrong driver named | 26.9% of runs | **2.8%** |
| Named the planted decoy | 16% | 1.3% |
| Correctly abstained when the data couldn't decide | 0% | **98%** |
| Primary driver found | 87.7% | 88.3% |
| Both causes in two-cause incidents | 28% | 59% |
| Abstained although a driver existed (our cost) | 0% | 9.3% |

Live Claude, one run per adversarial scenario (indicative only, n = 7): the competing-hypothesis investigator named
0 wrong drivers and abstained correctly 2/2. The original prompt named 1 wrong driver, which the server's re-test
rejected. Safety suite: 16/16 attack and failure cases, **0 unauthorized refunds**.

## Challenges
Our first "verified root cause" rule was wrong, and an audit proved it: shares of excess are normalised, so some
slice always passes, and a confounded channel became the root cause. Fixing that properly meant turning "the AI
checked its numbers" into "the system tried to prove the AI wrong". Then an independent review found that our own
fix was over-confident at small sample sizes. We switched to exact tests and corrected for every value scanned before
freezing the numbers.

## Accomplishments we're proud of
- An investigator that **abstains** when the data can't separate two explanations, instead of picking one.
- Business impact with **honest provenance labels** on every figure.
- A money path where the AI never holds a write tool.

## What we learned
On easy incidents AI doesn't beat a good SQL query, and claiming otherwise would be dishonest. The value is in
refusing to be fooled, and in making every claim checkable.

## What's next
Real carrier and inventory integrations for the response plan; Disputes API signals; multi-merchant tenancy;
calibration on real (non-synthetic) merchant histories.

## Limitations (stated plainly)
- Sandbox only; synthetic analytical history.
- The engine shows association, not causation, and was calibrated on scenarios we wrote. It needs volume.
- The live AI comparison is small.
- Response actions are manual.

## Built with
Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic, Next.js, React, TypeScript, AG Grid / AG Studio (incl. AG Studio
AI), PayPal REST APIs (Orders v2, Payments refunds, Webhooks), PayPal Agent Toolkit, Anthropic Claude API, Google
Gemini API (optional), Docker, Playwright, pytest.

## AI tools used to build it (disclosure)
Claude Code (Claude Opus) for engineering, review agents and documentation. Anthropic Claude API (runtime
investigator). AG Studio AI (in-product assistant). Google Gemini API (earlier runtime option).
**History:** this project evolved from our earlier hackathon prototype "Countersign" (refund guard); the
investigation, falsification engine, impact engine and incident workspace were built for this submission.

## Links
- Repository: https://github.com/shro-2002/payops-sentinel
- Demo video: https://youtu.be/5SXoGS8ZJnE (2:53, public)
- Prize categories to tick: Overall · Best Use of AG Grid (AG Studio) · Best Use of PayPal + AI
