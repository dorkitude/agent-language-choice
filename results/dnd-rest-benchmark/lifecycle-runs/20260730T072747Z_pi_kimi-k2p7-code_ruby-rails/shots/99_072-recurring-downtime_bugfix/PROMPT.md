```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: 072-recurring-downtime
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
        Use Ruby 4.0.5 and Rails 8.1.3. A minimal Rails API app is acceptable; implement the REST endpoints in Rails routes/controllers.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 072 Recurring Downtime

Preserve all earlier behavior. Add recurring downtime activities that campaign
members can allocate to owned characters and progress repeatedly.

## Downtime Activity Object

An activity response is exactly:

`{"activity_id":"activity-training","name":"Weapon training","cycles_required":2}`

`activity_id` and `name` must be nonempty strings. `cycles_required` must be an
integer from 1 through 10. Activity IDs must be unique within one campaign.

## Downtime Allocation Object

An allocation response is exactly:

`{"character_id":"play-char-w","activity_id":"activity-training","cycles_completed":0,"completions":0}`

`cycles_completed` tracks progress toward the next completion. `completions`
tracks how many times the recurring activity has completed for that character.

## Endpoints

`POST /v1/play/campaigns/{id}/downtime/activities`

Only the campaign DM may create downtime activities. Players receive 403.
Unknown campaigns return 404. Invalid payloads return 400. Duplicate activity
IDs return 409.

The request body is:

`{"activity_id":"activity-training","name":"Weapon training","cycles_required":2}`

A successful create returns 201 and the exact activity object.

`POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations`

Only the player who owns `character_id` may allocate downtime. The DM receives
403. Non-owners receive 403. Unknown characters or activities return 404.
Duplicate allocations for the same character and activity return 409.

The body is:

`{"activity_id":"activity-training"}`

A successful allocation returns 201 and the exact allocation object with
`cycles_completed:0` and `completions:0`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress`

Only the player who owns `character_id` may progress downtime. The DM receives
403. Non-owners receive 403. Unknown characters, activities, or allocations
return 404.

Each successful progress call increments `cycles_completed`. When
`cycles_completed` reaches the activity's `cycles_required`, the server resets
`cycles_completed` to 0 and increments `completions`. The allocation can then be
progressed again for another recurring completion.

The response is exactly the updated allocation object.

`GET /v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}`

Authenticated campaign members may read an allocation. Unknown characters,
activities, or allocations return 404. The response is exactly the allocation
object.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/072-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
