# 016 Analytics Reporting

Status: specified; evaluator suite added.

Spec: [`challenges/analytics-reporting.md`](../../experiments/dnd-rest-benchmark/challenges/analytics-reporting.md)  
Evaluator suite: `analytics-reporting`

## Request

A fresh maintenance agent inherits the audit/export-capable service and adds
deterministic campaign analytics APIs.

## Required Behaviors

- `GET /v1/campaigns/{id}/analytics/summary`
- `POST /v1/campaigns/{id}/analytics/risk-report`
- Return deterministic readiness, risk, and signal summaries over accumulated
  state

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 15. It is the first roadmap point that satisfies the
"fresh agent inherits a grown codebase at least 15 times" target.
