```text
You are participating in a staged programming-language benchmark.

        Target: ruby-stdlib
        Language: ruby
        Framework/runtime: stdlib
        Lifecycle stage: sqlite-storage
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
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Ruby 4.0.5 with the standard library only. Avoid Sinatra, Rails, Rack, and gems.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 4: SQLite Game Storage

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and move durable game-world and game-state data behind SQLite-backed
storage.

For this stage, the evaluator checks the API contract. The implementation
should also create a SQLite database file in the project directory, preferably
`game.db`, and should initialize schema on server startup.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Storage Status

`GET /v1/storage/status`

Rules:

- Report the durable storage driver.
- Report schema version `1`.
- Report whether the database has been initialized.

Response:

```json
{"driver": "sqlite", "schema_version": 1, "initialized": true}
```

## Reset Storage

`POST /v1/storage/reset`

Rules:

- Clear benchmark-created durable data.
- Recreate the schema.
- Preserve process health.

Response:

```json
{"ok": true, "schema_version": 1}
```




        Finish when ./run.sh is ready.
```
