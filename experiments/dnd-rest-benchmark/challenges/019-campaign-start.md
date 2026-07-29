# Maintenance Stage 19: Campaign Start

`POST /v1/play/campaigns/{id}/start` is DM-owner only. A lobby campaign with
at least two party members becomes active exactly once. Return
`{"id":"play-1","status":"active","current_actor":"player-a","turn_number":1}`.
Starting an active or under-populated campaign returns 409; a player receives
403.
