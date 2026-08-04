```text
You are participating in a staged programming-language benchmark.

        Target: javascript-node
        Language: javascript
        Framework/runtime: node-stdlib
        Lifecycle stage: 078-actor-audit-trail
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

        # 078 Actor Audit Trail

This cumulative suite inherits `077-gm-delegation`.

Preserve all earlier behavior. Add a campaign-scoped actor audit trail for
mutating campaign play events. For this ticket, automatic auditing is required
for the new audit mutation endpoint only; no retroactive auditing of earlier
mutation endpoints is required.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

An audit entry is exactly:

`{"kind":"note","actor":"player-a","role":"player","timestamp":1,"correlation_id":"corr-1"}`

`actor` is the authenticated username. `role` is `DM` for the campaign owner
and `player` for campaign members. `timestamp` is a deterministic per-campaign
sequence starting at 1 and incrementing for every created audit entry.
`correlation_id` must be unique per campaign.

## Create Audit Event

`POST /v1/play/campaigns/{id}/audit-events`

Authenticated campaign members, including the campaign owner, may create audit
events. The deterministic request body is:

`{"kind":"note","correlation_id":"corr-1"}`

`kind` and `correlation_id` must be nonempty strings. Invalid payloads return
400. Duplicate `correlation_id` values in the same campaign return 409.

Success creates an immutable audit record and returns 201 with the exact audit
entry.

## Read Audit Events

`GET /v1/play/campaigns/{id}/audit-events`

Only the campaign owner may read the audit trail. Non-owner campaign members
receive 403.

Returns immutable entries in timestamp order:

`{"entries":[{"kind":"note","actor":"dm","role":"DM","timestamp":1,"correlation_id":"corr-dm"},{"kind":"note","actor":"player-a","role":"player","timestamp":2,"correlation_id":"corr-player"}]}`



        Finish when ./run.sh is ready.
```
