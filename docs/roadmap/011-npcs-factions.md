# 011 NPCs And Factions

Status: specified; evaluator suite added.

Spec: [`challenges/npcs-factions.md`](../../experiments/dnd-rest-benchmark/challenges/npcs-factions.md)  
Evaluator suite: `npcs-factions`

## Request

A fresh maintenance agent inherits the quest-capable service and adds NPC,
faction, and relationship-state APIs.

## Required Behaviors

- `POST /v1/campaigns/{id}/factions`
- `POST /v1/campaigns/{id}/npcs`
- `GET /v1/campaigns/{id}/relationships`
- Preserve all campaign, quest, compendium, and DM behavior

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 10. It adds cross-entity relationships and tests
whether agents keep identifiers and aggregate counts coherent.
