# Maintenance Stage 34: Rest Turns

Preserve all earlier behavior. The active player may take a short or long rest
as an exploration turn.

`POST /v1/play/campaigns/{id}/turn/rest` accepts `{"type":"long"}` (or `"short"`).
Only the current actor may call it. Return 201 with a rest event:

```json
{
  "sequence": 9,
  "kind": "rest",
  "actor": "player-a",
  "type": "long",
  "hp_current": 20,
  "hp_max": 20,
  "next_actor": "dm"
}
```

A long rest sets the acting character's `hp_current` to `hp_max`. Acting out
of turn or an invalid type returns 400/409.
