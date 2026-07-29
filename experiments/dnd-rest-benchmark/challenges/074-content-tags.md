# 074 Content Tags

This cumulative suite inherits `073-session-zero-settings`.

Preserve all earlier behavior. Add campaign content records with deterministic
tags and role-appropriate tag filtering.

## Content Object

A content record response is exactly:

`{"content_id":"content-spider","kind":"scene","text":"A giant spider descends.","tags":["arachnophobia","combat"]}`

`content_id`, `kind`, and `text` must be nonempty strings. On creation, `tags`
must be a nonempty array of unique nonempty strings. Tag order is preserved
exactly as submitted.

## Endpoints

`POST /v1/play/campaigns/{id}/content`

Only the campaign DM may create content. Players receive 403. Unauthenticated
requests receive 401. Unknown campaigns return 404. Invalid payloads return
400. Duplicate `content_id` values within the campaign return 409.

The deterministic request body is:

`{"content_id":"content-spider","kind":"scene","text":"A giant spider descends.","tags":["arachnophobia","combat"]}`

A successful create returns 201 and the exact content object.

`PUT /v1/play/campaigns/{id}/content/{content_id}/tags`

Only the campaign DM may replace a content record's tags. Players receive 403.
Unauthenticated requests receive 401. Unknown campaigns or content IDs return
404. The request body is `{"tags":[...]}`. The replacement list may be empty;
when tags are present, each tag must be a unique nonempty string. Invalid
payloads return 400.

A successful update returns 200 and the exact updated content object.

`GET /v1/play/campaigns/{id}/content`

Authenticated campaign members may list content. Unknown campaigns return 404.
Results preserve creation order.

The optional `exclude_tag=TAG` query parameter excludes matching tagged content
from player responses. When present, `exclude_tag` must be a nonempty string or
the request returns 400. The campaign DM always receives all content records,
including records with `exclude_tag`. Players receive records that do not
contain `exclude_tag`. Without `exclude_tag`, all campaign members receive all
content records.
