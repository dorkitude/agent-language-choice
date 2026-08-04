```text
You are participating in a staged programming-language benchmark.

        Target: ruby-stdlib
        Language: ruby
        Framework/runtime: stdlib
        Lifecycle stage: 044-encounter-rewards
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
        Use Ruby 4.0.5 with the standard library only. Avoid Sinatra, Rails, Rack, and gems.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 44: Encounter Rewards

Preserve all earlier behavior. The owner awards deterministic XP and loot when
closing an encounter.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards` accepts
`{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}`. Only the owner may
award rewards. Return 200 with the reward record. Rewards may be awarded only once
per encounter; duplicates return 409.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/close` marks the encounter
`closed`. Only the owner may call it. Return 200 with
`{"id":"enc-road","status":"closed","xp_awarded":150}`. Closing before awarding
rewards is allowed but returns `xp_awarded: 0`.



        Finish when ./run.sh is ready.
```
