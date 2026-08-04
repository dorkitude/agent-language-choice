```text
You are participating in a staged programming-language benchmark.

        Target: typescript-vite
        Language: typescript
        Framework/runtime: vite
        Lifecycle stage: 086-pagination-search
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
        Use Vite 8.1.3 with TypeScript. Implement the REST API through Vite dev-server middleware or a Vite plugin; do not replace it with a plain Node-only server.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 086 Pagination/Search

This cumulative suite inherits `085-schema-migration`.

Preserve all earlier behavior. Add campaign search records with stable
pagination, filtering, and ordering. Search records are campaign-scoped and
preserve creation order.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Only the campaign DM may
create search records. The campaign DM and campaign members may list search
records; other authenticated users receive 403.

## Create Search Record

`POST /v1/play/campaigns/{id}/search-records`

The request body must contain nonempty `record_id` and `text`. `record_id` must
be unique within the campaign.

A valid request returns 201 with exact JSON:

`{"record_id":"record-1","text":"Goblin cave"}`

Invalid creation requests return 400 and must not create a record.
Authenticated non-DM actors receive 403.

## List Search Records

`GET /v1/play/campaigns/{id}/search-records`

Supported query parameters:

- `q`: optional case-insensitive substring filter over `text`
- `limit`: integer from 1 through 3, default `2`
- `cursor`: nonnegative integer offset into the filtered result set, default
  `0`

Invalid query values return 400.

The response preserves creation order after filtering, applies `cursor` and
`limit`, and returns exact JSON:

`{"records":[...],"next_cursor":N|null}`

`next_cursor` is the next filtered offset when more records remain, otherwise
`null`.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/086-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
