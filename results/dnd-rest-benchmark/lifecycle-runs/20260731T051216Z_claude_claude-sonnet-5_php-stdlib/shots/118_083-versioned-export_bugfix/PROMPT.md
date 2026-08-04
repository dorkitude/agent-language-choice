```text
You are participating in a staged programming-language benchmark.

        Target: php-stdlib
        Language: php
        Framework/runtime: stdlib
        Lifecycle stage: 083-versioned-export
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
        Use PHP 8.5.8 and the built-in PHP server. Do not add Composer packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 083 Versioned Export

This cumulative suite inherits `082-transaction-recovery`.

Preserve all earlier behavior. Add DM-only campaign exports that snapshot the
campaign's current public story and status into immutable, sequential versions.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Authenticated players,
including campaign members, cannot create or read exports and receive 403.

## Create Export

`POST /v1/play/campaigns/{id}/exports`

Only the campaign DM may create an export. The request body is empty. Each
successful call creates a new immutable snapshot whose version is one greater
than the campaign's previous export count. The snapshot captures exactly the
campaign document's current `story` and the campaign's current `status`.

For a campaign whose story is `The party reaches the glass gate.` and status is
`active`, the first export returns 201 with exact JSON:

`{"version":1,"story":"The party reaches the glass gate.","status":"active"}`

## List Exports

`GET /v1/play/campaigns/{id}/exports`

Only the campaign DM may list exports. The response is exact JSON with exports
ordered by ascending version:

`{"exports":[{"version":1,"story":"The party reaches the glass gate.","status":"active"},{"version":2,"story":"The glass gate opens to a blue stair.","status":"active"}]}`

## Read Export

`GET /v1/play/campaigns/{id}/exports/{version}`

Only the campaign DM may read a specific export. Existing versions return the
exact immutable snapshot. Unknown versions return 404.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/083-04.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
