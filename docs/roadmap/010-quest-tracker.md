# 010 Quest Tracker

Status: specified; evaluator suite added.

Spec: [`challenges/quest-tracker.md`](../../experiments/dnd-rest-benchmark/challenges/quest-tracker.md)  
Evaluator suite: `quest-tracker`

## Request

A fresh maintenance agent inherits the service after DM helper APIs and adds
campaign quest tracking.

## Required Behaviors

- `POST /v1/campaigns/{id}/quests`
- `POST /v1/campaigns/{id}/quests/{quest_id}/progress`
- `GET /v1/campaigns/{id}/quests/summary`
- Preserve all prior behavior while adding quest state

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 9. It tests whether agents can add a new campaign
subdomain after the codebase already contains auth, storage, campaign state,
rules, and DM tools.
