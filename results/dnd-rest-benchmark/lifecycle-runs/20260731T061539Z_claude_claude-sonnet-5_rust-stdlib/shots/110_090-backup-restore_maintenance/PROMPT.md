```text
You are participating in a staged programming-language benchmark.

        Target: rust-stdlib
        Language: rust
        Framework/runtime: stdlib
        Lifecycle stage: 090-backup-restore
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
        Use Rust 1.97.0 and the standard library only. Do not add Cargo dependencies or HTTP crates. Implement HTTP handling with std::net::TcpListener/TcpStream and serde-free JSON string handling.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 090 Backup and Restore

This cumulative suite inherits `089-readiness-health`.

Preserve all earlier behavior. Add owner-only campaign backups that snapshot
the current public campaign story and status, and restore exactly one existing
snapshot without mutating the snapshot itself.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Authenticated players,
including campaign members, cannot create, list, or restore backups and receive
403.

## Create Backup

`POST /v1/play/campaigns/{id}/backups`

Only the campaign DM may create a backup. The request body is empty. Each
successful call creates a new immutable snapshot whose `backup_id` is
sequential in the form `backup-1`, `backup-2`, and so on. The snapshot captures
exactly the campaign document's current public `story` and the campaign's
current `status`.

For a campaign whose story is `Story A: the party secures the old keep.` and
status is `active`, the first backup returns 201 with exact JSON:

`{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}`

## List Backups

`GET /v1/play/campaigns/{id}/backups`

Only the campaign DM may list backups. The response is exact JSON with backups
ordered by creation sequence:

`{"backups":[{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}]}`

Backups are immutable. Mutating the campaign document or restoring a backup
must not change any existing listed snapshot.

## Restore Backup

`POST /v1/play/campaigns/{id}/backups/{backup_id}/restore`

Only the campaign DM may restore a backup. Existing backups apply exactly the
snapshot's `story` and `status` to the campaign and return HTTP 200 with the
restored snapshot as exact JSON:

`{"backup_id":"backup-1","story":"Story A: the party secures the old keep.","status":"active"}`

Unknown backup IDs return 404. Restoring a backup must not duplicate event
identities or create a new backup snapshot.



        Finish when ./run.sh is ready.
```
