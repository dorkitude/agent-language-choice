```text
You are participating in a staged programming-language benchmark.

        Target: go-open
        Language: go
        Framework/runtime: open-modules
        Lifecycle stage: 059-npc-agendas
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
        Use Go 1.26.5. Third-party Go modules are allowed and should be recorded in go.mod/go.sum. Choose idiomatic libraries where they reduce implementation risk; for real SQLite support, prefer the pure-Go modernc.org/sqlite driver (or another compatible driver) rather than requiring CGO. Runtime network access remains forbidden.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 059 NPC Agendas

This cumulative suite inherits `058-loot-distribution`.

Preserve all earlier behavior. Add DM-managed campaign NPC records with a
private agenda and player-visible public status.

`POST /v1/play/campaigns/{id}/npcs` accepts:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"find-gundren","public_status":"searching"}`.

Only the campaign DM may create NPCs. `npc_id`, `name`, `agenda`, and
`public_status` are required nonempty strings. Duplicate `npc_id` values within
the same campaign return 409. A valid request creates the NPC and returns 201
with all fields:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"find-gundren","public_status":"searching"}`.

`PUT /v1/play/campaigns/{id}/npcs/{npc_id}/agenda` accepts:

`{"agenda":"reach-cragmaw","public_status":"traveling"}`.

Only the campaign DM may update an NPC agenda. `agenda` and `public_status` are
required nonempty strings. Unknown NPCs return 404. A valid update returns 200
with the full DM shape:

`{"npc_id":"npc-guide","name":"Sildar","agenda":"reach-cragmaw","public_status":"traveling"}`.

`GET /v1/play/campaigns/{id}/npcs/{npc_id}` is available to authenticated
campaign members. Unknown NPCs return 404. DM responses include `agenda`.
Player responses include only:

`{"npc_id":"npc-guide","name":"Sildar","public_status":"traveling"}`.

Player responses must never include `agenda`. Players cannot create or update
NPCs and receive 403 for those mutating requests.



        Finish when ./run.sh is ready.
```
