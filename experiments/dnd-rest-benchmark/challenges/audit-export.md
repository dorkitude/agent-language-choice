# Maintenance Stage 14: Audit And Export

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add deterministic audit and export APIs for campaign state.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Audit Log

`GET /v1/campaigns/{id}/audit`

Response:

```json
{
  "campaign_id": "camp-1",
  "events": 1,
  "quests": 1,
  "npcs": 1,
  "sessions": 1
}
```

## Export Campaign

`GET /v1/campaigns/{id}/export`

Response:

```json
{
  "campaign_id": "camp-1",
  "name": "Lost Mine",
  "characters": 1,
  "quests": 1,
  "npcs": 1,
  "inventory_items": 1,
  "sessions": 1,
  "schema_version": 1
}
```

The export is a deterministic JSON summary, not a file download.
