# 006 Monster And Item Compendium

Status: specified; evaluator suite added.

Spec: [`challenges/compendium.md`](../../experiments/dnd-rest-benchmark/challenges/compendium.md)  
Evaluator suite: `compendium`

## Request

Add persistent game-world storage for monster and item compendium records.

## Required Behaviors

- `POST /v1/compendium/monsters`
- `GET /v1/compendium/monsters/{slug}`
- `POST /v1/compendium/items`
- `GET /v1/compendium/items/{slug}`
- Preserve deterministic fields such as slug, name, challenge rating, armor
  class, hit points, tags, rarity, and item effects

## Prompt Role

Maintenance agent.

## Scoring Notes

This stage compounds storage with typed-ish domain objects. It should reveal
whether agents keep route naming, JSON field names, and persistence schemas
consistent as the codebase grows.

