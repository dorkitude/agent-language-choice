```text
You are participating in a staged programming-language benchmark.

        Target: ruby-stdlib
        Language: ruby
        Framework/runtime: stdlib
        Lifecycle stage: auth-users
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

        # Maintenance Stage 3: Users and Password Login

You are inheriting an existing D&D REST API codebase. Preserve every endpoint
from the core, character-rule, and combat-state suites and add deterministic
username/password APIs.

All success responses must be JSON. Invalid requests must return a non-2xx
status: use `400` for malformed input, `401` for bad credentials, and `409` for
duplicate usernames.

Security note for this benchmark: implement real password hashing when the
language/framework gives you a reasonable standard or framework-provided option.
If the target has no reasonable built-in option, isolate password handling
behind a small helper so a production hash can replace it. Do not store or echo
the plain password in API responses.

## Register User

`POST /v1/auth/register`

Request:

```json
{"username": "dm", "password": "swordfish", "role": "dm"}
```

Rules:

- `username` must be 2-32 characters, lowercase letters, digits, `_`, or `-`.
- `password` must be at least 8 characters.
- `role` must be either `dm` or `player`.
- A duplicate `username` returns HTTP 409.

Response:

```json
{"username": "dm", "role": "dm"}
```

## Login

`POST /v1/auth/login`

Request:

```json
{"username": "dm", "password": "swordfish"}
```

Rules:

- Correct credentials return a deterministic token for the benchmark:
  `session-<username>`.
- Bad credentials return HTTP 401.

Response:

```json
{"username": "dm", "token": "session-dm"}
```



            Previous deterministic failure report:

            ```text
            suite=auth-users base_url=http://127.0.0.1:65089 passed=false tests=23/24
PASS	health	0ms	HTTP 200
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
PASS	combat-create-session	0ms	HTTP 200
PASS	combat-add-condition	0ms	HTTP 200
PASS	combat-advance-to-mage	0ms	HTTP 200
PASS	combat-advance-to-fighter-decrements	0ms	HTTP 200
PASS	combat-advance-wrap-round	0ms	HTTP 200
PASS	combat-advance-condition-expires	0ms	HTTP 200
PASS	combat-advance-expired-removed	0ms	HTTP 200
FAIL	auth-register-user	8ms	HTTP 200	status 200, want 201
  response: {"username":"dm","role":"dm"}
PASS	auth-register-duplicate	0ms	HTTP 409
PASS	auth-login-user	8ms	HTTP 200
PASS	auth-login-bad-password	8ms	HTTP 401


Error: suite failed: 23/24 tests passed
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



failed test IDs: auth-register-user
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.


        Finish when ./run.sh is ready.
```
