```text
You are participating in a staged programming-language benchmark.

        Target: typescript-nextjs
        Language: typescript
        Framework/runtime: nextjs
        Lifecycle stage: 081-concurrent-turn-safety
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

        # 081 Concurrent Turn Safety

This cumulative suite inherits `080-idempotency-keys`.

Preserve all earlier behavior. Add a campaign-scoped safe turn submission
endpoint that rejects stale turn submissions without changing queue state.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Submit Safe Turn

`POST /v1/play/campaigns/{id}/safe-turns`

Authenticated campaign members, including the campaign owner, may submit safe
turn actions.

The deterministic request body is:

`{"submission_id":"submit-1","expected_turn":1,"action":"move"}`

`submission_id` and `action` must be nonempty strings. `expected_turn` must be
a positive integer. Invalid payloads return 400.

Per campaign safe-turn state starts at `current_turn` 1.

If `expected_turn` equals the campaign safe-turn `current_turn`, accept the
submission, advance exactly once, and return 201 with exact JSON:

`{"submission_id":"submit-1","action":"move","accepted_turn":1,"next_turn":2}`

Duplicate `submission_id` values are rejected with 409 and no state change.

If `expected_turn` differs from the current turn, reject the stale submission
with 409 and exact JSON:

`{"current_turn":2}`

Stale submissions must not advance the turn and must not appear in accepted
turn history.

## Read Safe Turns

`GET /v1/play/campaigns/{id}/safe-turns`

Campaign DM and members may read safe-turn state. The response is exact and
ordered by acceptance:

`{"current_turn":2,"accepted":[{"submission_id":"submit-1","action":"move","accepted_turn":1,"next_turn":2}]}`



        Finish when ./run.sh is ready.
```
