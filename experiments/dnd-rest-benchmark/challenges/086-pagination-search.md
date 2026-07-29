# 086 Pagination/Search

This cumulative suite inherits `085-schema-migration`.

Preserve all earlier behavior. Add campaign search records with stable
pagination, filtering, and ordering. Search records are campaign-scoped and
preserve creation order.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign DM may
create search records. The campaign DM and campaign members may list search
records; other authenticated users receive 403.

## Create Search Record

`POST /v1/play/campaigns/{id}/search-records`

The request body must contain nonempty `record_id` and `text`. `record_id` must
be unique within the campaign.

A valid request returns 201 with exact JSON:

`{"record_id":"record-1","text":"Goblin cave"}`

Invalid creation requests return 400 and must not create a record.
Authenticated non-DM actors receive 403.

## List Search Records

`GET /v1/play/campaigns/{id}/search-records`

Supported query parameters:

- `q`: optional case-insensitive substring filter over `text`
- `limit`: integer from 1 through 3, default `2`
- `cursor`: nonnegative integer offset into the filtered result set, default
  `0`

Invalid query values return 400.

The response preserves creation order after filtering, applies `cursor` and
`limit`, and returns exact JSON:

`{"records":[...],"next_cursor":N|null}`

`next_cursor` is the next filtered offset when more records remain, otherwise
`null`.
