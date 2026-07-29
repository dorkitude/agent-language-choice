# 068 Calendar and Weather

Preserve all earlier behavior. Add a campaign calendar that the DM initializes
once, advances in bounded day increments, and exposes to authenticated campaign
members with deterministic weather.

`POST /v1/play/campaigns/{id}/calendar` accepts:

`{"day":1,"season":"spring"}`

Only the campaign DM may initialize the calendar. Players receive 403. `day`
must be an integer greater than or equal to 1. `season` must be one of
`spring`, `summer`, `autumn`, or `winter`. Invalid payloads return 400.
Initializing an already initialized calendar for the same campaign returns 409.
Unknown campaigns return 404.

The response is exactly:

`{"day":1,"season":"spring","weather":"rain"}`

Weather is derived from the current `day` and `season` by this simple function:
assign season offsets `spring=0`, `summer=1`, `autumn=2`, `winter=3`; compute
`(day + season_offset) % 4`; map `0=clear`, `1=rain`, `2=wind`, `3=snow`.

`GET /v1/play/campaigns/{id}/calendar` is available to authenticated campaign
members, including the DM and joined players. It returns exactly:

`{"day":1,"season":"spring","weather":"rain"}`

If the calendar has not been initialized, GET returns 404.

`POST /v1/play/campaigns/{id}/calendar/advance` accepts:

`{"days":5}`

Only the campaign DM may advance the calendar. Players receive 403. `days` must
be an integer from 1 through 30. Advancing a noninitialized calendar returns
404. A successful advance increments the current day by `days` and returns the
new exact calendar object with deterministic weather.
