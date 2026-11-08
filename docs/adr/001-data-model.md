# ADR-001: PostgreSQL relational ledger, no graph database

- Date: 2026-11-08
- Status: Accepted

## Context
The graph-engineering method asks first whether a knowledge graph beats a simpler structure (stage 1, "scope &
value test"). A graph pays off for multi-hop questions over recurring entities whose relationships *are* the data.

PayOps Sentinel's questions are:
- refund rate per dimension value in a window (one GROUP BY),
- excess refunds per value vs its own baseline (two GROUP BYs),
- dimension A = x broken down by dimension B (one filtered GROUP BY — the deepest "hop" we need),
- capture → refunds → provider events (one-to-many foreign keys, depth 2).

## Decision
Use PostgreSQL with a normalized schema (captures, refunds, ledger_entries, paypal_events, incidents,
investigation_runs, agent_tool_calls, findings, evidence_records, remediation_cases, action_proposals,
approval_decisions, financial_executions, audit_events) with real foreign keys and CHECK/UNIQUE constraints.
JSONB only for raw provider payloads, tool results and detector metrics. No Neo4j, no GraphRAG, no vectors.

## Test that would reverse this
Introduce a graph only for a concrete multi-hop query SQL handles badly, e.g. "customers linked by shared device or
payout account across 3+ hops to a disputed capture" (fraud rings). No such query exists in P0/P1.

## Consequences
- Provenance is relational: every claim → evidence_record → agent_tool_call (stored result) → investigation_run →
  incident. Every refund → ledger_entry → (provider event | executor verification).
- The *development* process uses a task graph (docs/TASK_GRAPH.md); that is unrelated to the data model.
