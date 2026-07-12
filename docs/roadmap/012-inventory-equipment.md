# 012 Inventory And Equipment

Status: specified; evaluator suite added.

Spec: [`challenges/inventory-equipment.md`](../../experiments/dnd-rest-benchmark/challenges/inventory-equipment.md)  
Evaluator suite: `inventory-equipment`

## Request

A fresh maintenance agent inherits the NPC/faction-capable service and adds
party inventory plus equipment assignment APIs.

## Required Behaviors

- `POST /v1/campaigns/{id}/inventory`
- `POST /v1/campaigns/{id}/characters/{character_id}/equipment`
- `GET /v1/campaigns/{id}/inventory/summary`
- Preserve campaign character and compendium item semantics

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 11. It tests mutable quantities, ownership transfer,
and aggregation across compendium items and campaign characters.
