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
