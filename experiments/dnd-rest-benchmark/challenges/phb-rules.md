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
{"level": 5, "hp_current": 9, "hp_max": 35, "hit_dice_spent": 3, "exhaustion_level": 1}
```

Rules:

- Long rest restores current HP to max HP.
- Long rest restores spent hit dice up to half the character level, rounded
  down, minimum 1.
- Long rest reduces exhaustion by 1, to a minimum of 0.

Response:

```json
{"hp_current": 35, "hit_dice_spent": 1, "exhaustion_level": 0}
```

## Equipment Load

`POST /v1/phb/equipment-load`

Request:

```json
{"strength": 12, "weight": 181}
```

Rules:

- Carrying capacity is `strength * 15`.
- `encumbered` is true when carried weight exceeds capacity.

Response:

```json
{"capacity": 180, "weight": 181, "encumbered": true}
```
