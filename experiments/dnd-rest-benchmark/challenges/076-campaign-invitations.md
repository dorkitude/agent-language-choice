# 076 Campaign Invitations

This cumulative suite inherits `075-privacy-controls`.

Preserve all earlier behavior. Add campaign invitations so a campaign DM can
invite a registered player identity, and only that identity can accept the
invitation.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404.

An invitation object is exactly:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b","status":"pending"}`

`invitation_id`, `username`, and `character_id` must be nonempty strings.
Invitation IDs are unique per campaign. A campaign cannot have more than one
active `pending` invitation for the same target username. The target username
must be a registered user with role `player`.

## Create Invitation

`POST /v1/play/campaigns/{id}/invitations`

Only the campaign DM may create invitations. The deterministic request body is:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b"}`

Success returns 201 and the exact pending invitation object. Invalid payloads or
unknown/non-player target users return 400. Duplicate invitation IDs and
duplicate active invitations for the same user return 409.

## Accept Invitation

`POST /v1/play/campaigns/{id}/invitations/{invitation_id}/accept`

Only the invited target user may accept. Other campaign members and the campaign
DM receive 403. Unknown invitation IDs return 404. Repeating acceptance returns
409.

On first acceptance, the campaign member is added using the invitation's
`character_id`, and the invitation status changes to `accepted`. Success returns
200 and the exact accepted invitation object:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b","status":"accepted"}`

## List Invitations

`GET /v1/play/campaigns/{id}/invitations`

Returns `{"invitations":[...]}` in creation order. The campaign DM sees all
invitations. A target user sees only their own invitations, including before
they become a campaign member. Other campaign members see an empty list.
