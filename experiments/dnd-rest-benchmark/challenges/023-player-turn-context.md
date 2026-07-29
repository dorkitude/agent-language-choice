# Maintenance Stage 23: Player Turn Context

Add `GET /v1/play/campaigns/{id}/my-turn` for a campaign member with role
`player`. Return `is_my_turn`, `current_actor`, the caller's `{id,name}`
character, and `recent_events`. A player may read only their own character
context and never DM-private document fields.
