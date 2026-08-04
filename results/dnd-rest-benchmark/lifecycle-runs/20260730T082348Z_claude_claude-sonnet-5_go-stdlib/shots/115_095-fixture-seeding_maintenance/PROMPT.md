```text
You are participating in a staged programming-language benchmark.

        Target: go-stdlib
        Language: go
        Framework/runtime: stdlib
        Lifecycle stage: 095-fixture-seeding
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
        Use Go 1.26.5, net/http, and encoding/json. Do not add third-party packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 095 Fixture Seeding

This cumulative suite inherits `094-safety-boundaries`.

Preserve all earlier behavior. Add a campaign-scoped deterministic fixture
seeding surface under authenticated `/v1/play/campaigns/{id}`. All endpoints
use `Authorization: Bearer session-<username>`. Unauthenticated requests return
401. Unknown campaigns return 404. Non-member users return 403. The campaign DM
is considered a campaign member for reads.

## Seed Canonical Fixture

`POST /v1/play/campaigns/{id}/fixture-seeds`

Only the campaign DM may seed fixture state. Players receive 403.

The request body is:

`{"fixture_id":"canonical-v1"}`

`fixture_id` must be exactly `canonical-v1`. Missing, non-string, empty, or any
other value returns 400. Invalid fixture requests must not create or mutate
fixture state.

The first valid seed atomically creates the canonical fixture and returns 201
with exactly:

`{"fixture_id":"canonical-v1","status":"seeded","characters":[{"character_id":"fixture-hero","name":"Ari","class":"fighter"},{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}`

Repeating the same valid seed is idempotent: return 200 with the exact same
state and do not duplicate characters, events, or any other state.

## Read Fixture State

`GET /v1/play/campaigns/{id}/fixture-state`

Authenticated campaign members, including the DM, may read fixture state. If no
fixture has been seeded for the campaign, return 404.

After seeding, return the exact canonical fixture state:

`{"fixture_id":"canonical-v1","status":"seeded","characters":[{"character_id":"fixture-hero","name":"Ari","class":"fighter"},{"character_id":"fixture-mage","name":"Bea","class":"wizard"}],"story":"The lantern is lit.","event_ids":["fixture-event-1","fixture-event-2"]}`



        Finish when ./run.sh is ready.
```
