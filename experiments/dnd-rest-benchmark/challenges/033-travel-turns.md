# Maintenance Stage 33: Travel Turns

Preserve all earlier behavior. The active player may consume an exploration turn
to travel along a valid location edge.

`POST /v1/play/campaigns/{id}/turn/travel` accepts `{"destination_id":"cave"}`.
Only the current actor may call it, and only if the destination is a valid
outbound connection from the party's current location. Return 201 with a travel
event:

```json
{
  "sequence": 8,
  "kind": "travel",
  "actor": "player-b",
  "destination_id": "cave",
  "travel_turns": 1,
  "next_actor": "dm"
}
```

The location graph and current scene remain unchanged. Invalid destinations or
acting out of turn return 409.
