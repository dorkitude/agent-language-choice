# Maintenance Stage 9: Quest Tracker

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add campaign quest tracking APIs.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Create Quest

`POST /v1/campaigns/{id}/quests`

Request:

```json
{
  "id": "quest-1",
  "title": "Resolve goblin trail ambush",
  "status": "active",
  "milestones": ["Find the trail", "Confront the ambushers"]
}
```

Response:

```json
{
  "id": "quest-1",
  "title": "Resolve goblin trail ambush",
  "status": "active",
  "milestones_total": 2,
  "milestones_done": 0
}
```

## Update Quest Progress

`POST /v1/campaigns/{id}/quests/{quest_id}/progress`

Request:

```json
{"completed": ["Find the trail"]}
```

Response:

```json
{
  "id": "quest-1",
  "status": "active",
  "milestones_total": 2,
  "milestones_done": 1
}
```

## Quest Summary

`GET /v1/campaigns/{id}/quests/summary`

Response:

```json
{"campaign_id": "camp-1", "active": 1, "completed": 0, "blocked": 0}
```
