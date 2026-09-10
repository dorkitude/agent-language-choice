```text
You are participating in a staged programming-language benchmark.

        Target: java-stdlib
        Language: java
        Framework/runtime: stdlib
        Lifecycle stage: 058-loot-distribution
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
        Use OpenJDK 26.0.1 and only the Java standard library, such as com.sun.net.httpserver.HttpServer.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 058 Loot Distribution

This cumulative suite inherits `057-currency-and-trade`.

Preserve all earlier behavior. Add campaign-scoped loot records that the DM can
open, players can vote on, and the DM can assign exactly once.

`POST /v1/play/campaigns/{id}/loot` accepts:

`{"loot_id":"loot-1","item_id":"healing-potion","quantity":1}`.

Only the campaign DM may create loot. The `item_id` must be a known inventory
catalog item and `quantity` must be positive. A valid request creates an
immutable open loot record and returns 201:

`{"loot_id":"loot-1","item_id":"healing-potion","quantity":1,"status":"open"}`.

Duplicate `loot_id` values within the same campaign return 409.

`POST /v1/play/campaigns/{id}/loot/{loot_id}/votes` accepts:

`{"recipient_character_id":"play-char-b"}`.

Only authenticated campaign players may vote. The recipient must be a character
in the same campaign. Each player identity may cast one immutable vote per loot
record; duplicate or changed votes return 409. A valid vote returns 201:

`{"loot_id":"loot-1","voter":"player-a","recipient_character_id":"play-char-b","votes_for_recipient":1}`.

`POST /v1/play/campaigns/{id}/loot/{loot_id}/assign` has no body.

Only the campaign DM may assign loot. Assignment requires the loot to be open
and to have a single unambiguous highest vote recipient. Tied or voteless loot
returns 409. A valid assignment atomically adds the loot quantity to the
recipient character inventory, closes the loot, and returns 200:

`{"loot_id":"loot-1","recipient_character_id":"play-char-b","item_id":"healing-potion","quantity":1,"votes":2,"status":"assigned"}`.

Duplicate assignment attempts return 409 and must not add inventory again.

`GET /v1/play/campaigns/{id}/loot/{loot_id}` is available to authenticated
campaign members. Unknown loot returns 404. The response returns the immutable
record, including `loot_id`, `item_id`, `quantity`, `status`,
`recipient_character_id`, and `votes`.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/059-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
