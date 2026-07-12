# Maintenance Stage 10: NPCs And Factions

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add APIs for campaign NPCs, factions, and relationship state.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Create Faction

`POST /v1/campaigns/{id}/factions`

Request:

```json
{"id": "faction-1", "name": "Stonehill Inn", "stance": "friendly"}
```

Response:

```json
{"id": "faction-1", "name": "Stonehill Inn", "stance": "friendly"}
```

## Create NPC

`POST /v1/campaigns/{id}/npcs`

Request:

```json
{
  "id": "npc-1",
  "name": "Toblen Stonehill",
  "faction_id": "faction-1",
  "disposition": 2
}
```

Response:

```json
{
  "id": "npc-1",
  "name": "Toblen Stonehill",
  "faction_id": "faction-1",
  "disposition": 2
}
```

## Relationship Summary

`GET /v1/campaigns/{id}/relationships`

Response:

```json
{
  "campaign_id": "camp-1",
  "factions": 1,
  "npcs": 1,
  "friendly_npcs": 1
}
```
