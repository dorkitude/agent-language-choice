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

