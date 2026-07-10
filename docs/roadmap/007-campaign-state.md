# 007 Campaign State APIs

Status: specified; evaluator suite added.

Spec: [`challenges/campaign-state.md`](../../experiments/dnd-rest-benchmark/challenges/campaign-state.md)  
Evaluator suite: `campaign-state`

## Request

Add persistent campaign, character, and event-log APIs for ongoing campaign
state.

## Required Behaviors

- `POST /v1/campaigns`
- `POST /v1/campaigns/{id}/characters`
- `POST /v1/campaigns/{id}/events`
- `GET /v1/campaigns/{id}/state`
- Return deterministic campaign summaries with character lists and log counts

## Prompt Role

Maintenance agent.

## Scoring Notes

This is the first stage where prior user/auth concepts, storage concepts, and
game-domain state all interact. It tests whether agents can extend a schema and
preserve API shape under a more realistic application boundary.

