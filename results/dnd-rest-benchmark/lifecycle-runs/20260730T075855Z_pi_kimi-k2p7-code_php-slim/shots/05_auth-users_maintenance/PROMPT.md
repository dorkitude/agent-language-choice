```text
You are participating in a staged programming-language benchmark.

        Target: php-slim
        Language: php
        Framework/runtime: slim
        Lifecycle stage: auth-users
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



        Finish when ./run.sh is ready.
```
