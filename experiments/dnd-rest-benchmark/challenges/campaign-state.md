# Maintenance Stage 6: Campaign State APIs

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add SQLite-backed APIs for campaign state.

All success responses must be JSON. Invalid requests must return a non-2xx
status, preferably `400` for malformed input, `404` for unknown records, and
`409` for duplicate IDs.

## Create Campaign

`POST /v1/campaigns`

Request:

```json
{"id": "camp-1", "name": "Lost Mine", "dm": "dm"}
```

Response:

```json
{"id": "camp-1", "name": "Lost Mine", "dm": "dm"}
```

## Add Character

`POST /v1/campaigns/camp-1/characters`

Request:

```json
{
  "id": "char-1",
  "name": "Nyx",
  "player": "dm",
  "level": 3,
  "class": "rogue"
}
```

Response:

```json
{"id": "char-1", "name": "Nyx", "level": 3, "class": "rogue"}
```

## Add Session Log Event

`POST /v1/campaigns/camp-1/events`

Request:

```json
{"id": "evt-1", "kind": "note", "text": "The party reached Phandalin."}
```

Response:

```json
{"id": "evt-1", "kind": "note"}
```

## Read Campaign State

`GET /v1/campaigns/camp-1/state`

Response:

```json
{
  "id": "camp-1",
  "name": "Lost Mine",
  "dm": "dm",
  "characters": [
    {"id": "char-1", "name": "Nyx", "level": 3, "class": "rogue"}
  ],
  "log_count": 1
}
```

