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
  "campaign_id": "camp-1",
  "party": [{"level": 3}, {"level": 3}, {"level": 3}, {"level": 3}],
  "monster_slugs": ["goblin", "goblin", "goblin"]
}
```

Rules:

- Look up monster CR from the compendium.
- Reuse the adjusted-XP math from the core suite.
- Return a deterministic recommendation for the encounter.

Response:

```json
{
  "campaign_id": "camp-1",
  "base_xp": 150,
  "adjusted_xp": 300,
  "difficulty": "easy",
  "monster_count": 3,
  "recommendation": "safe warm-up"
}
```

## Loot Parcel

`POST /v1/dm/loot-parcel`

Request:

```json
{"campaign_id": "camp-1", "tier": 1, "seed": 42}
```

For this benchmark, return deterministic tier-1 loot.

Response:

```json
{
  "campaign_id": "camp-1",
  "coins_gp": 75,
  "items": [{"slug": "healing-potion", "quantity": 2}]
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
  "summary": "Nyx scouts the goblin trail.",
  "open_threads": ["Resolve goblin trail ambush"]
}
```
