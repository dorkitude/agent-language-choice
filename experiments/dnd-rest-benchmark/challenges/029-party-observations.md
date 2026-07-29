# Maintenance Stage 29: Party Observations

Any authenticated member can post an append-only observation to
`POST /v1/play/campaigns/{id}/observations` with
`{"type":"world","text":"..."}`. Return 201 with sequence, kind
`observation`, actor, type, and text. Require nonempty type and text.
