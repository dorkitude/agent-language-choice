```text
You are participating in a staged programming-language benchmark.

        Target: python-stdlib
        Language: python
        Framework/runtime: stdlib
        Lifecycle stage: 085-schema-migration
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
        Use Python 3.14.6 standard library only, such as http.server and json.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 085 Schema Migration

This cumulative suite inherits `084-import-validation`.

Preserve all earlier behavior. Add DM-only campaign schema migrations that
accept only legacy schema version 1 snapshots and deterministically migrate
them to schema version 2.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign DM may
create migrations or read migrated state; other authenticated users receive
403.

## Migrate Snapshot

`POST /v1/play/campaigns/{id}/migrations`

The request body must contain `schema_version` and `story`. The only valid input
schema version is `1`. `story` must be nonempty.

Invalid migrations return 400 and must not change migrated state. A valid
migration preserves `story`, sets `schema_version` to `2`, sets
`campaign_name` to the campaign's name, and returns 201 with exact JSON:

`{"schema_version":2,"story":"Legacy story","campaign_name":"Legacy Game"}`

Repeating the same valid version 1 source snapshot is idempotent: it returns 200
with the same migrated state and does not create a new state.

## Read Migrated State

`GET /v1/play/campaigns/{id}/migration-state`

Only the campaign DM may read the current migrated state. Before the first
successful migration, this endpoint returns 404. After a successful migration,
it returns exact JSON:

`{"schema_version":2,"story":"Legacy story","campaign_name":"Legacy Game"}`



        Finish when ./run.sh is ready.
```
