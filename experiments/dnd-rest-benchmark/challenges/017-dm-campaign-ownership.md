# Maintenance Stage 17: DM Campaign Ownership

Preserve every prior endpoint. Add a protected campaign-play surface under
`/v1/play`. Protected requests use `Authorization: Bearer session-<username>`.
Return `401` for missing/invalid credentials and `403` for a valid actor
without permission.

## Create Play Campaign

`POST /v1/play/campaigns` accepts `{"id":"play-1","name":"Ashen Road","max_players":2}`.
Only an authenticated `dm` may create it. Return HTTP 201 with
`{"id":"play-1","name":"Ashen Road","owner":"dm","status":"lobby","max_players":2}`.
Reject duplicate IDs with 409.
