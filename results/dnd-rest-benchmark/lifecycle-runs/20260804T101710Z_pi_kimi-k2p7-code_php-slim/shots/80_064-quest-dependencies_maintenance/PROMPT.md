```text
You are participating in a staged programming-language benchmark.

        Target: php-slim
        Language: php
        Framework/runtime: slim
        Lifecycle stage: 064-quest-dependencies
        Shot kind: maintenance

        You are a fresh maintenance agent inheriting this existing codebase. Add the requested feature stage while preserving all existing API behavior.

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
        Use PHP 8.5.8, Composer 2.10.2, Slim 4.15.2, and slim/psr7 1.8.0.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 064 Quest Dependencies

This cumulative suite inherits `063-secrets-and-clues`.

Preserve all earlier behavior. Add deterministic campaign quest records whose
activation is gated by completed prerequisite quests.

`POST /v1/play/campaigns/{id}/quests` accepts:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[]}`

or the same shape with `depends_on` containing existing quest IDs.

Only the campaign DM may create quests. Players receive 403 for creation.
`quest_id` and `title` are required nonempty strings. `depends_on` must be a
JSON array of unique quest IDs. Dependencies cannot include the quest's own ID
and every dependency must already exist in the same campaign. Invalid
dependency lists return 400. Quest IDs are unique per campaign; duplicates
return 409.

A valid quest create returns 201 exactly:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[],"state":"locked"}`

`PUT /v1/play/campaigns/{id}/quests/{quest_id}/state` accepts:

`{"state":"active"}`

or:

`{"state":"completed"}`

Only the campaign DM may change quest state. Players receive 403 for state
changes. Unknown quests return 404. `state` must be exactly `active` or
`completed`; invalid state values return 400.

Allowed transitions are:

- `locked` to `active`, only when every quest in `depends_on` has state
  `completed`.
- `active` to `completed`.

All other transitions return 409. A successful state change returns 200 with
the full quest record:

`{"quest_id":"quest-scout","title":"Scout the cave","depends_on":[],"state":"active"}`

`GET /v1/play/campaigns/{id}/quests` is available to authenticated campaign
members and returns:

`{"quests":[...]}`

Quests are returned in creation order. Each quest uses the exact creation
response shape with its current `state`.



        Finish when ./run.sh is ready.
```
