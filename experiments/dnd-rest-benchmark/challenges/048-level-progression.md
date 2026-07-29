# Maintenance Stage 48: Level Progression

Preserve all earlier behavior. Apply deterministic level-up thresholds and
class resources.

`POST /v1/play/campaigns/{id}/characters/{char_id}/level-up` accepts
`{"level":2}`. Only the owner may call it. The level must be exactly one higher
than the current level. Return 200 with the updated character:

```json
{
  "character_id": "play-char-a",
  "level": 2,
  "hp_max": 15,
  "hit_dice": "1d8",
  "proficiency_bonus": 2
}
```

Rogues gain `1d8 + con_modifier` max HP per level beyond 1. Missing or non-owner
requests return 400/403.
