# Maintenance Stage 24: GM Turn Context

Add owner-only `GET /v1/play/campaigns/{id}/gm/status`. Return
`needs_attention`, `current_actor`, party member summaries, and recent events.
`needs_attention` is true exactly when the current actor is the owner. Players
receive 403.
