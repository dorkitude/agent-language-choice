# Maintenance Stage 12: Downtime Crafting

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add deterministic downtime crafting APIs.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Create Crafting Project

`POST /v1/campaigns/{id}/downtime/crafting`

Request:

```json
{
  "id": "craft-1",
  "character_id": "char-1",
  "item_slug": "healing-potion",
  "days_required": 2,
  "cost_gp": 25
}
```

Response:

```json
{
  "id": "craft-1",
  "character_id": "char-1",
  "item_slug": "healing-potion",
  "days_required": 2,
  "days_completed": 0,
  "status": "active"
}
```

## Advance Crafting

`POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance`

Request:

```json
{"days": 2}
```

Response:

```json
{
  "id": "craft-1",
  "days_completed": 2,
  "status": "complete"
}
```

When the project completes, the crafted item should be available in the
campaign inventory.
