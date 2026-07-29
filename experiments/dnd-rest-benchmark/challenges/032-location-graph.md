# Maintenance Stage 32: Location Graph

Preserve all earlier behavior. The owner builds a deterministic location graph
for the campaign under `/v1/play/campaigns/{id}/locations`.

## Create location

`POST /v1/play/campaigns/{id}/locations` accepts `{"id":"cave","name":"Wave Echo Cave"}`.
Only the owner may call it. Return 201 with the created location.
Duplicate IDs return 409.

## Create connection

`POST /v1/play/campaigns/{id}/locations/{from_id}/connections` accepts
`{"to_id":"cave","travel_turns":1}`. Only the owner may call it. Return 201
with `{"from_id":"town","to_id":"cave","travel_turns":1}`. Reject connections
to missing locations or already-connected destinations with 400.

## Read valid travel

`GET /v1/play/campaigns/{id}/locations/{loc_id}/travel` returns valid outbound
connections for any campaign member:
`{"destinations":[{"id":"cave","name":"Wave Echo Cave","travel_turns":1}]}`.
