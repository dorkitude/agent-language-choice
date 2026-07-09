# Maintenance Stage 2: Stateful Combat

You are inheriting an existing D&D REST API codebase. Preserve every endpoint
from the core and character-rule suites and add the endpoints below.

All state may be in memory. State only needs to last for the lifetime of the
server process.

All success responses must be JSON. Invalid requests must return a non-2xx
status, preferably `400` for malformed input and `404` for unknown session IDs.

## Create Combat Session

`POST /v1/combat/sessions`

Request:

```json
{
  "id": "enc-1",
  "combatants": [
    {"name": "fighter", "dex": 1, "roll": 13},
    {"name": "rogue", "dex": 3, "roll": 14},
    {"name": "mage", "dex": 2, "roll": 14}
  ]
}
```

Rules:

- `id` is client-supplied and must uniquely identify the session.
- Initiative score is `roll + dex`.
- Sort initiative by score descending, then dex descending, then name ascending.
- New sessions start at `round = 1` and `turn_index = 0`.
- `active` is the combatant at the current `turn_index`.

Response:

```json
{
  "id": "enc-1",
  "round": 1,
  "turn_index": 0,
  "active": {"name": "rogue", "score": 17},
  "order": [
    {"name": "rogue", "score": 17},
    {"name": "mage", "score": 16},
    {"name": "fighter", "score": 14}
  ]
}
```

## Add Condition

`POST /v1/combat/sessions/{id}/conditions`

Request:

```json
{
  "target": "fighter",
  "condition": "blessed",
  "duration_rounds": 2
}
```

Rules:

- `target` must name a combatant in the session.
- `condition` is an arbitrary string.
- `duration_rounds` must be a positive integer.
- Conditions are attached to the named combatant.

Response:

```json
{
  "target": "fighter",
  "conditions": [
    {"condition": "blessed", "remaining_rounds": 2}
  ]
}
```

## Advance Turn

`POST /v1/combat/sessions/{id}/advance`

Rules:

- Advance `turn_index` to the next combatant.
- When the turn index wraps from the end of the initiative order back to `0`,
  increment `round`.
- At the start of a combatant's turn, decrement each condition attached to that
  active combatant.
- Remove a condition when its remaining duration reaches `0`.
- Conditions on inactive combatants do not decrement.

Response shape:

```json
{
  "id": "enc-1",
  "round": 1,
  "turn_index": 1,
  "active": {"name": "mage", "score": 16},
  "conditions": {
    "fighter": [
      {"condition": "blessed", "remaining_rounds": 2}
    ]
  }
}
```
