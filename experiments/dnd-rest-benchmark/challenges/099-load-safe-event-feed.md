# 099 Load-Safe Event Feed

This cumulative suite inherits `098-spectator-view`.

Add an authenticated campaign-member append-only event feed with cursor
pagination that remains stable when new events are appended between reads. Do
not add ticket 100 behavior.

## Append Feed Events

`POST /v1/play/campaigns/{id}/feed-events`

Authentication: authenticated campaign members only, including the DM owner and
joined players.

Request body:

```json
{"event_id":"feed-1","text":"A"}
```

`event_id` and `text` must be nonempty strings. `event_id` must be unique
within the campaign feed.

Success status: `201 Created`

Exact success response:

```json
{"event_id":"feed-1","text":"A","sequence":1}
```

`sequence` is one-based accepted append order. Duplicate `event_id` returns
`409`. Invalid request bodies return `400`. Missing authentication returns
`401`. Authenticated nonmembers return `403`.

## Read Event Feed

`GET /v1/play/campaigns/{id}/event-feed?cursor=N&limit=N`

Authentication: authenticated campaign members only.

Both query parameters are optional. Defaults are `cursor=0` and `limit=2`.
`cursor` is the zero-based count of events already consumed and must be an
integer `>= 0`. `limit` must be an integer from `1` through `3`. Invalid
pagination parameters return `400`.

Exact success response:

```json
{"events":[...],"next_cursor":2}
```

`events` are accepted events in append order, each shaped exactly as
`{"event_id":"feed-1","text":"A","sequence":1}`. `next_cursor` is `cursor`
plus the returned event count. If `cursor` is greater than or equal to the
current feed length, return:

```json
{"events":[],"next_cursor":N}
```

Reads must never mutate the feed.

The evaluator verifies this load-safe interleaving:

1. Append `feed-1`/`A`, `feed-2`/`B`, and `feed-3`/`C`.
2. Read `cursor=0&limit=2` and receive `[feed-1, feed-2]`,
   `next_cursor=2`.
3. Append `feed-4`/`D`.
4. Read `cursor=2&limit=2` and receive `[feed-3, feed-4]`,
   `next_cursor=4`.
5. Read `cursor=4` and receive an empty page with `next_cursor=4`.
