```text
You are participating in a staged programming-language benchmark.

        Target: php-slim
        Language: php
        Framework/runtime: slim
        Lifecycle stage: 060-faction-reputation
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

        # 060 Faction Reputation

This cumulative suite inherits `059-npc-agendas`.

Preserve all earlier behavior. Add campaign faction creation and bounded
character reputation history.

`POST /v1/play/campaigns/{id}/factions` accepts:

`{"faction_id":"faction-harpers","name":"Harpers"}`.

Only the campaign DM may create factions. `faction_id` and `name` are required
nonempty strings. Duplicate `faction_id` values within the same campaign return
409. A valid request creates the faction and returns 201 exactly:

`{"faction_id":"faction-harpers","name":"Harpers"}`.

`POST /v1/play/campaigns/{id}/factions/{faction_id}/reputation` accepts:

`{"character_id":"play-char-w","delta":15,"reason":"rescued-prisoners"}`.

Only the campaign DM may change reputation. Unknown factions return 404.
`character_id` must identify a campaign member character. `delta` must be a
nonzero integer in `[-25,25]`. `reason` is a required nonempty string. The
stored total reputation for each faction/character pair is bounded to
`[-100,100]`. Each accepted change stores an immutable history record and
returns 201 exactly:

`{"faction_id":"faction-harpers","character_id":"play-char-w","reputation":15,"delta":15,"reason":"rescued-prisoners"}`.

`GET /v1/play/campaigns/{id}/factions/{faction_id}/reputation` is available to
authenticated campaign members. Unknown factions return 404. The response shape
is:

`{"faction_id":"faction-harpers","entries":[...]}`

The DM sees all history entries in insertion order. Each entry is exactly:

`{"faction_id","character_id","reputation","delta","reason"}`

Players see only entries for their own campaign character. Players cannot
create factions or change reputation and receive 403 for those mutating
requests.



        Finish when ./run.sh is ready.
```
