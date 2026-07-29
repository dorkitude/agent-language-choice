# 098 Spectator View

This cumulative suite inherits `097-agent-onboarding`.

Add read-only spectator access for campaign play. Do not add later-ticket
features and do not add spectator mutation endpoints.

## Spectator Tokens

`POST /v1/play/campaigns/{id}/spectators`

Authentication: DM campaign owner only.

Request body:

```json
{"spectator_id":"watcher-1"}
```

`spectator_id` must be a nonempty string and globally unique across spectator
tickets, because the bearer token contains only the spectator ID.

Success status: `201 Created`

Exact success response:

```json
{"spectator_id":"watcher-1","token":"spectator-watcher-1"}
```

Duplicate spectator IDs return `409`. Player session tokens return `403`.
Missing authentication returns `401`.

## Spectator Projection

`GET /v1/play/campaigns/{id}/spectator-view`

Authentication: exclusively `Authorization: Bearer spectator-<id>`.

Exact response for the suite fixture:

```json
{"campaign_id":"play-098","name":"Spectator Game","status":"lobby","party_size":1,"story":""}
```

The response must expose no member names, character IDs, private notes, chat,
tokens, ownership, or internal IDs. It must be repeat-stable and must not mutate
campaign state.

Missing or invalid spectator tokens return `401`. Normal DM or player session
tokens return `403` for this special public projection. A valid spectator token
for a different campaign returns `403`. An unknown campaign with a valid-shaped
spectator ticket returns `404`.
