```text
You are participating in a staged programming-language benchmark.

        Target: javascript-node
        Language: javascript
        Framework/runtime: node-stdlib
        Lifecycle stage: 057-currency-and-trade
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
        Use Node 26.4.0 built-in HTTP APIs and plain JavaScript modules. Do not use TypeScript, frameworks, or third-party packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 057 Currency and Trade

This cumulative suite inherits `056-consumables`.

Preserve all earlier behavior. Add deterministic per-character gold balances
and atomic character-to-character transfers within a campaign.

Each campaign character begins with exactly 10 gold when the character joins a
campaign.

`GET /v1/play/campaigns/{id}/characters/{character_id}/currency` is available
to authenticated campaign members. Unknown campaign characters return 404. A
valid response returns 200:

`{"character_id":"play-char-w","gold":10}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/currency/transfers`
accepts:

`{"to_character_id":"play-char-b","gold":3}`.

Only the source character owner may transfer gold. Non-owners return 403.

The destination must be a different character in the same campaign. Unknown
destinations, same-character destinations, and non-positive gold amounts return
400.

If the source character has insufficient gold, return 409 and leave both source
and destination balances unchanged.

A valid transfer debits and credits atomically, assigns a deterministic
campaign-local transfer id starting at 1, and returns 201:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","gold":3,"from_gold":7,"to_gold":13,"transfer_id":1}`.



        Finish when ./run.sh is ready.
```
