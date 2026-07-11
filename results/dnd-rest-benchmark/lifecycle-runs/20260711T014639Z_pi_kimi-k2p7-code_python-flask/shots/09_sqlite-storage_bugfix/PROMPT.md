```text
You are participating in a staged programming-language benchmark.

        Target: python-flask
        Language: python
        Framework/runtime: flask
        Lifecycle stage: sqlite-storage
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
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Python 3.14.6 and Flask 3.1.3. Implement the REST API as Flask routes.

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




            Previous deterministic failure report:

            ```text
            suite=sqlite-storage base_url=http://127.0.0.1:50937 passed=false tests=25/26
PASS	health	1ms	HTTP 200
PASS	dice-stats-2d6-plus-3	0ms	HTTP 200
PASS	dice-stats-1d20-minus-1	0ms	HTTP 200
PASS	dice-stats-invalid	0ms	HTTP 400
PASS	ability-check-failure	0ms	HTTP 200
PASS	ability-check-success	0ms	HTTP 200
PASS	encounter-adjusted-xp	0ms	HTTP 200
PASS	initiative-order	0ms	HTTP 200
PASS	ability-modifier-negative	0ms	HTTP 200
PASS	ability-modifier-high	0ms	HTTP 200
PASS	ability-modifier-invalid	0ms	HTTP 400
PASS	proficiency-level-boundary	0ms	HTTP 200
PASS	derived-stats	0ms	HTTP 200
PASS	combat-create-session	2ms	HTTP 200
PASS	combat-add-condition	1ms	HTTP 200
PASS	combat-advance-to-mage	1ms	HTTP 200
PASS	combat-advance-to-fighter-decrements	0ms	HTTP 200
PASS	combat-advance-wrap-round	1ms	HTTP 200
PASS	combat-advance-condition-expires	1ms	HTTP 200
FAIL	combat-advance-expired-removed	1ms	HTTP 200	conditions: missing JSON key "fighter"
  response: {"active":{"name":"fighter","score":14},"conditions":{},"id":"enc-1","round":2,"turn_index":2}
PASS	auth-register-user	80ms	HTTP 201
PASS	auth-register-duplicate	1ms	HTTP 409
PASS	auth-login-user	76ms	HTTP 200
PASS	auth-login-bad-password	77ms	HTTP 401
PASS	storage-status	1ms	HTTP 200
PASS	storage-reset	7ms	HTTP 200


Error: suite failed: 25/26 tests passed
Usage:
  dndeval run [flags]

Flags:
      --base-url string   Target server base URL (default "http://127.0.0.1:8080")
      --fail-fast         Stop at first failed test
  -h, --help              help for run
      --json-out string   Write JSON report to this path
      --suite string      Suite ID (default "core")
      --timeout string    Per-request timeout (default "3s")
  -v, --verbose           Show response details for passed tests



failed test IDs: combat-advance-expired-removed
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.


        Finish when ./run.sh is ready.
```
