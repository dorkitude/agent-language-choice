# Maintenance Stage 15: Analytics Reporting

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add deterministic campaign analytics APIs that summarize the
long-lived campaign codebase state.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Campaign Analytics Summary

`GET /v1/campaigns/{id}/analytics/summary`

Response:

```json
{
  "campaign_id": "camp-1",
  "readiness_score": 85,
  "open_quests": 1,
  "friendly_npcs": 1,
  "scheduled_sessions": 1,
  "inventory_items": 1
}
```

## Maintenance Risk Report

`POST /v1/campaigns/{id}/analytics/risk-report`

Request:

```json
{"include_zeroes": true}
```

Response:

```json
{
  "campaign_id": "camp-1",
  "risk_level": "low",
  "missing": [],
  "signals": {
    "has_dm": true,
    "has_characters": true,
    "has_next_session": true,
    "has_active_quest": true
  }
}
```

The goal is deterministic aggregation over the state accumulated across all
previous stages.
