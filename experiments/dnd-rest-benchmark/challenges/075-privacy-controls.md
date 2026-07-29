# 075 Privacy Controls

This cumulative suite inherits `074-content-tags`.

Preserve all earlier behavior. Add role-filtered privacy controls for campaign
notes, character-to-character whispers, and basic character sheets.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Authenticated users who are
neither the campaign DM nor a campaign member return 403.

## Notes

A note object is exactly:

`{"note_id":"note-a","text":"secret","visibility":"private","owner":"player-a"}`

`note_id` and `text` must be nonempty strings. `visibility` must be either
`private` or `party`. The server derives `owner` from the authenticated actor;
clients cannot choose another owner. Note IDs are unique per campaign.

`POST /v1/play/campaigns/{id}/notes`

Authenticated campaign members may create notes:

`{"note_id":"note-a","text":"secret","visibility":"private"}`

Success returns 201 and the exact note object. Invalid payloads return 400.
Duplicate note IDs return 409.

`GET /v1/play/campaigns/{id}/notes`

Returns `{"notes":[...]}` in creation order. The campaign DM sees all notes.
Players see all `party` notes and only their own `private` notes.

`GET /v1/play/campaigns/{id}/notes/{note_id}`

Returns the exact note object when readable. Unknown note IDs return 404.
Private notes return 403 to campaign members who are not the owner. The DM can
read every note.

`PUT /v1/play/campaigns/{id}/notes/{note_id}`

Only the note owner may update `text` and `visibility`; the campaign DM may
read all notes but does not override ownership. The request body is
`{"text":"...","visibility":"private"}` or `{"text":"...","visibility":"party"}`.
Invalid payloads return 400. Unknown note IDs return 404. Non-owners return
403. Success returns 200 and the exact updated note object.

## Whispers

A whisper object is exactly:

`{"whisper_id":"whisper-a","from_character_id":"play-char-a","to_character_id":"play-char-b","text":"meet at dawn"}`

`whisper_id`, `to_character_id`, and `text` must be nonempty strings. The sender
must be a campaign player with an owned character; `from_character_id` is
derived from that actor. `to_character_id` must belong to a current campaign
member. Whisper IDs are unique per campaign.

`POST /v1/play/campaigns/{id}/whispers`

The deterministic request body is:

`{"whisper_id":"whisper-a","to_character_id":"play-char-b","text":"meet at dawn"}`

Success returns 201 and the exact whisper object. Invalid payloads return 400.
Duplicate whisper IDs return 409.

`GET /v1/play/campaigns/{id}/whispers`

Returns `{"whispers":[...]}` in creation order. The campaign DM sees all
whispers. Players see only whispers where their owned character is either
`from_character_id` or `to_character_id`.

## Character Sheets

`GET /v1/play/campaigns/{id}/characters/{character_id}/sheet`

Only the character owner and campaign DM may read a sheet. Other campaign
members receive 403. Unknown character IDs return 404.

The deterministic basic sheet response is exactly:

`{"character_id":"play-char-a","owner":"player-a","name":"Aria","class":"rogue","level":1,"proficiency_bonus":2,"hp_max":10,"armor_class":10}`
