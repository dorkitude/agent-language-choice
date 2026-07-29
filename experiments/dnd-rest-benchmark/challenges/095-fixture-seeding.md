# 095 Fixture Seeding

This cumulative suite inherits `094-safety-boundaries`.

Preserve all earlier behavior. Add a campaign-scoped deterministic fixture
seeding surface under authenticated `/v1/play/campaigns/{id}`. All endpoints
use `Authorization: Bearer session-<username>`. Unauthenticated requests return
401. Unknown campaigns return 404. Non-member users return 403. The campaign DM
is considered a campaign member for reads.

## Seed Canonical Fixture

`POST /v1/play/campaigns/{id}/fixture-seeds`

Only the campaign DM may seed fixture state. Players receive 403.

The request body is:

`{"fixture_id":"canonical-v1"}`

`fixture_id` must be exactly `canonical-v1`. Missing, non-string, empty, or any
other value returns 400. Invalid fixture requests must not create or mutate
fixture state.

The first valid seed atomically creates the canonical fixture and returns 201
with exactly:

`{"fixture_id":"canonical-v1","status":"seeded","characters":[{"character_id":"fixture-hero","name":"Ari","class":"fighter"},{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}`

Repeating the same valid seed is idempotent: return 200 with the exact same
state and do not duplicate characters, events, or any other state.

## Read Fixture State

`GET /v1/play/campaigns/{id}/fixture-state`

Authenticated campaign members, including the DM, may read fixture state. If no
fixture has been seeded for the campaign, return 404.

After seeding, return the exact canonical fixture state:

`{"fixture_id":"canonical-v1","status":"seeded","characters":[{"character_id":"fixture-hero","name":"Ari","class":"fighter"},{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}`
