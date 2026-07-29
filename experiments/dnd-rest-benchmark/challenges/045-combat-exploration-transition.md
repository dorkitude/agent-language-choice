# Maintenance Stage 45: Combat/Exploration Transition

Preserve all earlier behavior. After a closed encounter, the campaign returns
to its exploration turn queue.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/end` closes the encounter if
still active and restores the campaign to the exploration phase. Only the owner
may call it. Return 200 with
`{"campaign_id":"play-1","status":"active","phase":"exploration","current_actor":"dm"}`.

The exploration queue resumes from the actor it had before combat began. If the
campaign was not in combat, return 409.
