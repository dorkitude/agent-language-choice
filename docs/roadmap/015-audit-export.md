# 015 Audit And Export

Status: specified; evaluator suite added.

Spec: [`challenges/audit-export.md`](../../experiments/dnd-rest-benchmark/challenges/audit-export.md)  
Evaluator suite: `audit-export`

## Request

A fresh maintenance agent inherits the session-capable service and adds
deterministic audit and export APIs for campaign state.

## Required Behaviors

- `GET /v1/campaigns/{id}/audit`
- `GET /v1/campaigns/{id}/export`
- Return deterministic counts across campaign events, quests, NPCs, inventory,
  sessions, and schema version

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 14. It tests whether agents can expose a stable summary
over a large, heterogeneous codebase without breaking prior routes.
