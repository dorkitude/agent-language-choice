```text
You are participating in a staged programming-language benchmark.

        Target: typescript-node
        Language: typescript
        Framework/runtime: node-stdlib
        Lifecycle stage: 098-spectator-view
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
        Use TypeScript 7.0.2 and Node 26.4.0 built-in HTTP APIs. Do not add frameworks.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 098 Spectator View

This cumulative suite inherits `097-agent-onboarding`.

Add read-only spectator access for campaign play. Do not add later-ticket
features and do not add spectator mutation endpoints.

## Spectator Tokens

`POST /v1/play/campaigns/{id}/spectators`

Authentication: DM campaign owner only.

Request body:

```json
{"spectator_id":"watcher-1"}
```

`spectator_id` must be a nonempty string and globally unique across spectator
tickets, because the bearer token contains only the spectator ID.

Success status: `201 Created`

Exact success response:

```json
{"spectator_id":"watcher-1","token":"spectator-watcher-1"}
```

Duplicate spectator IDs return `409`. Player session tokens return `403`.
Missing authentication returns `401`.

## Spectator Projection

`GET /v1/play/campaigns/{id}/spectator-view`

Authentication: exclusively `Authorization: Bearer spectator-<id>`.

Exact response for the suite fixture:

```json
{"campaign_id":"play-098","name":"Spectator Game","status":"lobby","party_size":1,"story":""}
```

The response must expose no member names, character IDs, private notes, chat,
tokens, ownership, or internal IDs. It must be repeat-stable and must not mutate
campaign state.

Missing or invalid spectator tokens return `401`. Normal DM or player session
tokens return `403` for this special public projection. A valid spectator token
for a different campaign returns `403`. An unknown campaign with a valid-shaped
spectator ticket returns `404`.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/098-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
