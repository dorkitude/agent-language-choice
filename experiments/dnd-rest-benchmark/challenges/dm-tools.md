# Maintenance Stage 8: DM Tools

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add DM-facing APIs that combine stored compendium and campaign
state.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Encounter Builder

`POST /v1/dm/encounter-builder`

Request:

```json
{
  "party_levels": [3, 3, 3, 3],
  "monsters": [{"slug": "goblin", "count": 4}]
}
```

Rules:

- Look up monster CR from the compendium.
- Reuse the adjusted-XP math from the core suite.
- Return threshold warnings for the encounter.

Response:

```json
{
  "base_xp": 200,
  "monster_count": 4,
  "multiplier": 2,
  "adjusted_xp": 400,
  "difficulty": "easy",
  "warnings": []
}
```

## Loot Parcel

`POST /v1/dm/loot-parcel`

Request:

```json
{"tier": 1, "seed": "camp-1-session-1"}
```

For this benchmark, return deterministic tier-1 loot.

Response:

```json
{
  "tier": 1,
  "coins": {"gp": 25, "sp": 40},
  "items": ["healing-potion"]
}
```

## Session Recap

`POST /v1/dm/session-recap`

Request:

```json
{"campaign_id": "camp-1"}
```

Response:

```json
{
  "campaign_id": "camp-1",
  "summary": "Lost Mine: 1 logged event, 1 active character."
}
```

