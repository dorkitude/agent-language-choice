# 071 Recipe Catalog

Preserve all earlier behavior. Add campaign crafting recipes with deterministic
ingredient requirements backed by the public campaign inventory item catalog.

## Recipe Object

A recipe response is exactly:

`{"recipe_id":"recipe-antitoxin","name":"Antitoxin","ingredients":{"healing-potion":2},"output_item":"torch","output_quantity":1}`

`recipe_id` and `name` must be nonempty strings. `ingredients` must be a
nonempty JSON object whose keys are valid campaign inventory item catalog IDs
and whose values are positive integer quantities. `output_item` must be a valid
campaign inventory item catalog ID. `output_quantity` must be a positive
integer. Recipe IDs must be unique within one campaign.

## Endpoints

`POST /v1/play/campaigns/{id}/recipes`

Only the campaign DM may create recipes. Players receive 403. Unknown campaigns
return 404. Invalid payloads return 400. Duplicate recipe IDs return 409.

The request body is:

`{"recipe_id":"recipe-antitoxin","name":"Antitoxin","ingredients":{"healing-potion":2},"output_item":"torch","output_quantity":1}`

A successful create returns 201 and the exact recipe object.

`GET /v1/play/campaigns/{id}/recipes`

Authenticated campaign members may list recipes. Responses preserve recipe
creation order and return exactly:

`{"recipes":[{"recipe_id":"recipe-antitoxin","name":"Antitoxin","ingredients":{"healing-potion":2},"output_item":"torch","output_quantity":1}]}`

`POST /v1/play/campaigns/{id}/recipes/{recipe_id}/craft`

Only the player who owns `character_id` may craft. The DM receives 403.
Non-owners receive 403. Unknown recipes or characters return 404.

The body is:

`{"character_id":"play-char-w"}`

The character must have at least every required ingredient quantity in their
inventory. Insufficient ingredients return 409 and must not partially mutate
state. A successful craft atomically consumes all ingredients, adds
`output_quantity` of `output_item`, and returns exactly:

`{"character_id":"play-char-w","recipe_id":"recipe-antitoxin","output_item":"torch","output_quantity":1}`
