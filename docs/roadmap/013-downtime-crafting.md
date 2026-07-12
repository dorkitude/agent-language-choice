# 013 Downtime Crafting

Status: specified; evaluator suite added.

Spec: [`challenges/downtime-crafting.md`](../../experiments/dnd-rest-benchmark/challenges/downtime-crafting.md)  
Evaluator suite: `downtime-crafting`

## Request

A fresh maintenance agent inherits the inventory-capable service and adds
downtime crafting projects with deterministic progress accounting.

## Required Behaviors

- `POST /v1/campaigns/{id}/downtime/crafting`
- `POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`
- Mark projects complete when enough days have elapsed
- Make completed crafted items available to campaign inventory

## Prompt Role

Maintenance agent.

## Scoring Notes

This is inheritance step 12. It compounds inventory, characters, persistent
state, and deterministic time/progress accounting.
