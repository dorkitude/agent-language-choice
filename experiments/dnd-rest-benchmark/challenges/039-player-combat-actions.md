# Maintenance Stage 39: Player Combat Actions

Preserve all earlier behavior. The current combatant submits typed combat
actions that are recorded but do not themselves advance the encounter turn.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/actions` accepts
`{"type":"attack","target":"goblin-1","text":"I strike with my rapier."}`.
Valid types are `attack`, `help`, `dodge`, and `ready`. Only the current
combatant may call it. Return 201 with the action event:

```json
{
  "sequence": 9,
  "kind": "combat_action",
  "actor": "player-a",
  "type": "attack",
  "target": "goblin-1",
  "text": "I strike with my rapier."
}
```

Invalid types or acting out of turn return 400/409.
