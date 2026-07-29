# Maintenance Stage 26: GM Resolution

When the current actor is the owner, only the owner can call
`POST /v1/play/campaigns/{id}/resolutions` with `{"text":"..."}`. Append a
`resolution` event and advance to player B. Return 201 with `next_actor` and
the incremented `turn_number`. A player attempting resolution receives 409.
