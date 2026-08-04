```text
You are participating in a staged programming-language benchmark.

        Target: ruby-sinatra
        Language: ruby
        Framework/runtime: sinatra
        Lifecycle stage: 077-gm-delegation
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
- rust: 1.97.0
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Ruby 4.0.5, Sinatra 4.2.1, Rack 3.2.6, and Puma 8.0.2.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 077 GM Delegation

This cumulative suite inherits `076-campaign-invitations`.

Preserve all earlier behavior. Add campaign-scoped GM delegation so the
campaign owner can grant and revoke limited co-GM authority for an existing
campaign member. The only delegated power in this ticket is `narrate`.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404.

A delegation record is exactly:

`{"username":"player-b","powers":["narrate"],"active":true}`

An inactive revoked delegation record is exactly:

`{"username":"player-b","powers":["narrate"],"active":false}`

`username` must be a campaign member. `powers` must be a nonempty array of
unique valid values. For this ticket, the only valid value is `narrate`.

## Grant Delegation

`POST /v1/play/campaigns/{id}/delegations`

Only the campaign owner may grant delegation. The deterministic request body is:

`{"username":"player-b","powers":["narrate"]}`

Success returns 201 and the exact active delegation record. Invalid payloads,
unknown/non-member targets, empty powers, duplicate powers, and powers other
than `narrate` return 400. A duplicate active delegate for the same username
returns 409. Non-owner campaign members receive 403.

An active delegate with `narrate` may use the existing
`POST /v1/play/campaigns/{id}/narrations` endpoint. Nondelegated players still
receive 403 from that endpoint.

## Revoke Delegation

`DELETE /v1/play/campaigns/{id}/delegations/{username}`

Only the campaign owner may revoke delegation. Success returns 200 and the exact
inactive delegation record. After revocation, the target user can no longer
narrate and receives 403 from `POST /v1/play/campaigns/{id}/narrations`.

## Audit

`GET /v1/play/campaigns/{id}/delegations/audit`

Only the campaign owner may read delegation audit. Non-owner campaign members
receive 403.

Returns immutable entries in grant/revoke order:

`{"entries":[{"username":"player-b","action":"granted","powers":["narrate"]},{"username":"player-b","action":"revoked","powers":["narrate"]}]}`



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/077-05.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
