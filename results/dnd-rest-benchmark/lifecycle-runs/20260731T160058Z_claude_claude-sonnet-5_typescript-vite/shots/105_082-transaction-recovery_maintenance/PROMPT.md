```text
You are participating in a staged programming-language benchmark.

        Target: typescript-vite
        Language: typescript
        Framework/runtime: vite
        Lifecycle stage: 082-transaction-recovery
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

        # 082 Transaction Recovery

This cumulative suite inherits `081-concurrent-turn-safety`.

Preserve all earlier behavior. Add a campaign-scoped transactional currency
transfer endpoint where failed compound mutations leave no partial debit,
credit, or transfer record.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return 403.

## Create Transactional Transfer

`POST /v1/play/campaigns/{id}/transactional-transfers`

Only the player who owns `from_character_id` may create the transfer. The
destination must be a different character in the same campaign. The amount
must be a positive integer and the source character must have sufficient gold.
Invalid character IDs, self-transfers, malformed payloads, and non-positive
amounts return 400. Insufficient balance returns 409.

The deterministic request body is:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"simulate_failure":false}`

If `simulate_failure` is true, the server must validate and prepare the
operation, then return 500 with exact JSON:

`{"error":"simulated failure"}`

The simulated failure must not change either character balance and must not
append a transfer record.

On success, debit and credit are committed together, append one ordered
success record, and return 201 with exact JSON:

`{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"from_gold":7,"to_gold":12,"sequence":1}`

## Read Transactional Transfers

`GET /v1/play/campaigns/{id}/transactional-transfers`

Campaign DM and members may read successful transactional transfers. Failed
simulated operations must never appear. The response is exact and ordered by
successful transfer sequence:

`{"transfers":[{"from_character_id":"play-char-w","to_character_id":"play-char-b","amount":2,"from_gold":7,"to_gold":12,"sequence":1}]}`



        Finish when ./run.sh is ready.
```
