# Maintenance Stage 7: Selected PHB Rules

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add deterministic endpoints for selected Player's Handbook-style
rules.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Spell Slots

`POST /v1/phb/spell-slots`

Request:

```json
{"class": "wizard", "level": 5}
```

For this benchmark, support wizard level 5.

Response:

```json
{"class": "wizard", "level": 5, "slots": {"1": 4, "2": 3, "3": 2}}
```

## Long Rest

`POST /v1/phb/rests/long`

Request:

```json
{"hp_current": 7, "hp_max": 24, "hit_dice_spent": 3, "hit_dice_max": 5}
```

Rules:

- Long rest restores current HP to max HP.
- Long rest restores spent hit dice up to half the maximum, rounded down,
  minimum 1.

Response:

```json
{"hp_current": 24, "hp_max": 24, "hit_dice_spent": 1, "hit_dice_max": 5}
```

## Equipment Load

`POST /v1/phb/equipment-load`

Request:

```json
{"strength": 16, "carried_lb": 180}
```

Rules:

- Carrying capacity is `strength * 15`.
- `encumbered` is true when carried pounds exceed capacity.

Response:

```json
{"carrying_capacity_lb": 240, "carried_lb": 180, "encumbered": false}
```

