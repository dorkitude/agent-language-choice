```text
You are participating in a staged programming-language benchmark.

        Target: php-stdlib
        Language: php
        Framework/runtime: stdlib
        Lifecycle stage: 065-quest-rewards
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
        Use PHP 8.5.8 and the built-in PHP server. Do not add Composer packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 065 Quest Rewards

This cumulative suite inherits `064-quest-dependencies`.

Preserve all earlier behavior. Add configured quest rewards that can be awarded
exactly once after quest completion.

`PUT /v1/play/campaigns/{id}/quests/{quest_id}/rewards` accepts:

`{"xp":100,"items":{"healing-potion":1}}`

Only the campaign DM may configure quest rewards. Players receive 403. Unknown
quests return 404. The quest must exist and have state `locked` or `active`;
completed quests reject configuration with 409. `xp` must be a nonnegative
integer. `items` must be a JSON object whose keys are valid catalog item IDs and
whose values are positive integer quantities. Invalid reward bodies return 400.

A valid configure request returns 200 with the full quest record including
rewards:

`{"quest_id":"quest-reward","title":"Recover the cache","depends_on":[],"state":"active","rewards":{"xp":100,"items":{"healing-potion":1}}}`

`POST /v1/play/campaigns/{id}/quests/{quest_id}/rewards/award` has no request
body.

Only the campaign DM may award quest rewards. Players receive 403. Unknown
quests return 404. The quest state must be `completed` and rewards must already
be configured; otherwise the request returns 409. A successful award grants the
configured XP and items once to every campaign member and returns 201 exactly:

`{"quest_id":"quest-reward","awarded":true,"xp":100,"items":{"healing-potion":1}}`

A repeat award returns 409 and makes no changes.

`GET /v1/play/campaigns/{id}/characters/{character_id}/rewards` is available to
authenticated campaign members. Unknown characters return 404. A valid request
returns cumulative quest reward grants for that character:

`{"character_id":"play-char-w","xp":100,"items":{"healing-potion":1}}`



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/066-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
