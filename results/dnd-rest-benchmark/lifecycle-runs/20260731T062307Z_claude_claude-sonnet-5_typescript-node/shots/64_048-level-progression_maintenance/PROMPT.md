```text
You are participating in a staged programming-language benchmark.

        Target: typescript-node
        Language: typescript
        Framework/runtime: node-stdlib
        Lifecycle stage: 048-level-progression
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

        # Maintenance Stage 48: Level Progression

Preserve all earlier behavior. Apply deterministic level-up thresholds and
class resources.

`POST /v1/play/campaigns/{id}/characters/{char_id}/level-up` accepts
`{"level":2}`. Only the owner may call it. The level must be exactly one higher
than the current level. Return 200 with the updated character:

```json
{
  "character_id": "play-char-a",
  "level": 2,
  "hp_max": 15,
  "hit_dice": "1d8",
  "proficiency_bonus": 2
}
```

Rogues gain `1d8 + con_modifier` max HP per level beyond 1. Missing or non-owner
requests return 400/403.



        Finish when ./run.sh is ready.
```
