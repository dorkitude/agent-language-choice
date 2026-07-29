# 087 Rate Limits

This cumulative suite inherits `086-pagination-search`.

Preserve all earlier behavior. Add deterministic, per-identity campaign rate
events. Each authenticated campaign member has an independent allowance of two
accepted rate events per campaign.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. The campaign DM and campaign
members may create and list rate events; other authenticated users receive 403.

## Create Rate Event

`POST /v1/play/campaigns/{id}/rate-events`

The request body must contain nonempty `event_id`. `event_id` must be unique
globally within the campaign.

A valid request records the event in acceptance order and returns 201 with
exact JSON:

`{"event_id":"rate-1","actor":"player-a","remaining":1}`

Each username has a fixed limit of 2 accepted events per campaign. When the
actor has no remaining allowance, the request returns 429 with exact JSON:

`{"limit":2,"remaining":0}`

Rejected rate-limited requests must not record an event. Invalid creation
requests return 400 and must not create an event.

## List Rate Events

`GET /v1/play/campaigns/{id}/rate-events`

Allowed campaign members receive accepted events in creation order plus the
caller's remaining allowance:

`{"events":[{"event_id":"rate-1","actor":"player-a"}],"remaining":1}`
