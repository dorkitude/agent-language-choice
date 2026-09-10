```text
You are participating in a staged programming-language benchmark.

        Target: ruby-sinatra
        Language: ruby
        Framework/runtime: sinatra
        Lifecycle stage: 071-recipe-catalog
        Shot kind: bugfix

        You are a fresh bug-fix agent inheriting this existing codebase after a deterministic evaluator failure.

        Use the exact latest runtime/framework versions already pinned in this
        workspace. Do not downgrade packages or replace the requested framework.

        Relevant version pins:
        - @types/node: 26.1.1
- @types/react: 19.2.17
- @types/react-dom: 19.2.3
- @vitejs/plugin-react: 6.0.3
- composer: 2.10.2
- django: 6.0.7
- flask: 3.1.3
- go: 1.26.5
- next: 16.2.10
- node: 26.4.0
- openjdk: 26.0.1
- php: 8.5.8
- puma: 8.0.2
- python: 3.14.6
- rack: 3.2.6
- rackup: 2.3.1
- rails: 8.1.3
- react: 19.2.7
- react-dom: 19.2.7
- ruby: 4.0.5
- rust: 1.97.0
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Ruby 4.0.5, Sinatra 4.2.1, Rack 3.2.6, and Puma 8.0.2.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

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



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/071-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
