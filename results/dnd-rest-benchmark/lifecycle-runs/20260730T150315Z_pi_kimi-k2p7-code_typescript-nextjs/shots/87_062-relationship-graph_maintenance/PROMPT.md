```text
You are participating in a staged programming-language benchmark.

        Target: typescript-nextjs
        Language: typescript
        Framework/runtime: nextjs
        Lifecycle stage: 062-relationship-graph
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
        Use Next.js 16.2.10, React 19.2.7, and TypeScript 7.0.2. Implement endpoints as Next route handlers under app/.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 062 Relationship Graph

This cumulative suite inherits `061-npc-dialogue`.

Preserve all earlier behavior. Add a directed relationship graph among campaign
entities. Campaign entities are exactly campaign member character IDs and NPC
IDs.

`POST /v1/play/campaigns/{id}/relationships` accepts:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":25}`.

Only the campaign DM may create relationship edges. Players receive 403 for
creation. Both `source_id` and `target_id` must name existing campaign entities,
the IDs must differ, `kind` must be a nonempty string, and `score` must be an
integer from -100 through 100. Unknown campaign entities return 404. Invalid
self-edges, empty kinds, missing fields, and out-of-range or non-integer scores
return 400. Creating a duplicate directed `(source_id, target_id, kind)` edge
returns 409.

A valid create returns 201 exactly:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":25}`.

`PUT /v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}`
accepts:

`{"score":60}`.

Only the campaign DM may update relationship edges. Players receive 403 for
updates. The addressed relationship edge must already exist, otherwise the
request returns 404. The score must be an integer from -100 through 100. A valid
update returns 200 with the full updated edge exactly:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":60}`.

`GET /v1/play/campaigns/{id}/relationships` is available to authenticated
campaign members and returns all edges in insertion order:

`{"edges":[...]}`

Each edge in the response is the exact full edge shape:

`{"source_id":"npc-guide","target_id":"play-char-w","kind":"trust","score":60}`.



        Finish when ./run.sh is ready.
```
