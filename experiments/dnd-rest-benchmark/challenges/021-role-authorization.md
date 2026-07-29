# Maintenance Stage 21: Role Authorization

Enforce bearer identity and campaign membership on the play surface. Add
`GET /v1/play/campaigns/{id}/turn`, returning
`campaign_id`, `current_actor`, `phase`, and `turn_number` to the owner or a
member. Missing auth is 401; an authenticated non-member is 403. Keep all
pre-play legacy endpoints backward compatible.
