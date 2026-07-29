# 091 Deterministic Replay

This cumulative suite inherits `090-backup-restore`.

Preserve all earlier behavior. Add a deterministic replay stream for campaign
members. Replay events are campaign-scoped, authenticated, ordered by
successful append order, and rebuild a public replay state without randomness.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return
403. The campaign DM and campaign members may append replay events and read
replay state.

## Append Replay Event

`POST /v1/play/campaigns/{id}/replay-events`

The deterministic request body is:

`{"event_id":"replay-1","kind":"append","text":"A"}`

`event_id` and `text` must be nonempty strings. `event_id` must be unique
within the campaign replay stream. `kind` must be exactly `append`; other
kinds return 400. Duplicate `event_id` values return 409 and must not mutate
replay state.

Successful appends return 201 with exact JSON containing creation sequence:

`{"event_id":"replay-1","kind":"append","text":"A","sequence":1}`

## Read Replay

`GET /v1/play/campaigns/{id}/replay`

Authenticated campaign members read exact deterministic replay state. The
`story` is the ordered concatenation of all append event `text` values.
`event_ids` is the ordered list of successful replay event IDs. `digest` is a
simple deterministic hash substitute defined as:

`strings.Join(event_ids, ",") + "|" + story`

After appending `replay-1` with text `A` and `replay-2` with text `B`, the
exact response is:

`{"story":"AB","event_ids":["replay-1","replay-2"],"digest":"replay-1,replay-2|AB"}`

## Check Replay

`GET /v1/play/campaigns/{id}/replay/check`

Returns the same exact deterministic state as `GET /replay`. This endpoint is
an explicit replay verification path and must not mutate state.
