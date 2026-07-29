# Maintenance Stage 31: Scene State

Preserve all earlier behavior. The owner may create, enter, and close scenes
for a campaign under `/v1/play/campaigns/{id}/scenes`.

## Create scene

`POST /v1/play/campaigns/{id}/scenes` accepts `{"id":"cave-entrance","name":"Cave Entrance"}`.
Only the owner may call it. Return HTTP 201 with `{"id":"cave-entrance","name":"Cave Entrance","status":"open"}`.
Duplicate scene IDs return 409.

## Enter scene

`POST /v1/play/campaigns/{id}/scenes/{scene_id}/enter` sets the campaign's
current scene. Only the owner may call it. Return 200 with
`{"current_scene_id":"cave-entrance","name":"Cave Entrance"}`. Closed scenes
may not be entered.

## Close scene

`POST /v1/play/campaigns/{id}/scenes/{scene_id}/close` marks the scene
`closed`. Only the owner may call it. Return 200 with
`{"id":"cave-entrance","status":"closed"}`.

## Read current scene

`GET /v1/play/campaigns/{id}/scenes/current` returns the open current scene
for any campaign member: `{"id":"cave-entrance","name":"Cave Entrance","status":"open"}`.
If none is set, return 404.
