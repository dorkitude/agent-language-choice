# Maintenance Stage 13: Session Scheduling

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add campaign session scheduling APIs.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Schedule Session

`POST /v1/campaigns/{id}/sessions`

Request:

```json
{
  "id": "sess-1",
  "starts_at": "2026-07-19T19:00:00Z",
  "duration_minutes": 180,
  "agenda": ["Goblin trail", "Stonehill Inn fallout"]
}
```

Response:

```json
{
  "id": "sess-1",
  "starts_at": "2026-07-19T19:00:00Z",
  "duration_minutes": 180,
  "agenda_count": 2
}
```

## Record Attendance

`POST /v1/campaigns/{id}/sessions/{session_id}/attendance`

Request:

```json
{"present": ["char-1"], "absent": []}
```

Response:

```json
{"session_id": "sess-1", "present_count": 1, "absent_count": 0}
```

## Next Session

`GET /v1/campaigns/{id}/sessions/next`

Response:

```json
{"id": "sess-1", "starts_at": "2026-07-19T19:00:00Z", "agenda_count": 2}
```
