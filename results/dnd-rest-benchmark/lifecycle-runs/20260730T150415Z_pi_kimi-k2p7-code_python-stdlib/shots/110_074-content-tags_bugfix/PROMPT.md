```text
You are participating in a staged programming-language benchmark.

        Target: python-stdlib
        Language: python
        Framework/runtime: stdlib
        Lifecycle stage: 074-content-tags
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
        Use Python 3.14.6 standard library only, such as http.server and json.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 074 Content Tags

This cumulative suite inherits `073-session-zero-settings`.

Preserve all earlier behavior. Add campaign content records with deterministic
tags and role-appropriate tag filtering.

## Content Object

A content record response is exactly:

`{"content_id":"content-spider","kind":"scene","text":"A giant spider descends.","tags":["arachnophobia","combat"]}`

`content_id`, `kind`, and `text` must be nonempty strings. On creation, `tags`
must be a nonempty array of unique nonempty strings. Tag order is preserved
exactly as submitted.

## Endpoints

`POST /v1/play/campaigns/{id}/content`

Only the campaign DM may create content. Players receive 403. Unauthenticated
requests receive 401. Unknown campaigns return 404. Invalid payloads return
400. Duplicate `content_id` values within the campaign return 409.

The deterministic request body is:

`{"content_id":"content-spider","kind":"scene","text":"A giant spider descends.","tags":["arachnophobia","combat"]}`

A successful create returns 201 and the exact content object.

`PUT /v1/play/campaigns/{id}/content/{content_id}/tags`

Only the campaign DM may replace a content record's tags. Players receive 403.
Unauthenticated requests receive 401. Unknown campaigns or content IDs return
404. The request body is `{"tags":[...]}`. The replacement list may be empty;
when tags are present, each tag must be a unique nonempty string. Invalid
payloads return 400.

A successful update returns 200 and the exact updated content object.

`GET /v1/play/campaigns/{id}/content`

Authenticated campaign members may list content. Unknown campaigns return 404.
Results preserve creation order.

The optional `exclude_tag=TAG` query parameter excludes matching tagged content
from player responses. When present, `exclude_tag` must be a nonempty string or
the request returns 400. The campaign DM always receives all content records,
including records with `exclude_tag`. Players receive records that do not
contain `exclude_tag`. Without `exclude_tag`, all campaign members receive all
content records.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/074-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
