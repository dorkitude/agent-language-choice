# 014 Session Scheduling

Status: specified; evaluator suite added.

Spec: [`challenges/session-scheduling.md`](../../experiments/dnd-rest-benchmark/challenges/session-scheduling.md)  
Evaluator suite: `session-scheduling`

## Request

A fresh maintenance agent inherits the downtime-capable service and adds
campaign session scheduling and attendance APIs.

## Required Behaviors

- `POST /v1/campaigns/{id}/sessions`
- `POST /v1/campaigns/{id}/sessions/{session_id}/attendance`
- `GET /v1/campaigns/{id}/sessions/next`
- Preserve campaign state, quest state, and inventory behavior

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 13. It introduces deterministic schedule state and a
new "next item" query over accumulated campaign data.
