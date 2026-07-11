```text
You are participating in a staged programming-language benchmark.

        Target: go-stdlib
        Language: go
        Framework/runtime: stdlib
        Lifecycle stage: dm-tools
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

        # Maintenance Stage 8: DM Tools

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add DM-facing APIs that combine stored compendium and campaign
state.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Encounter Builder

`POST /v1/dm/encounter-builder`

Request:

```json
{
  "campaign_id": "camp-1",
  "party": [{"level": 3}, {"level": 3}, {"level": 3}, {"level": 3}],
  "monster_slugs": ["goblin", "goblin", "goblin"]
}
```

Rules:

- Look up monster CR from the compendium.
- Reuse the adjusted-XP math from the core suite.
- Return a deterministic recommendation for the encounter.

Response:

```json
{
  "campaign_id": "camp-1",
  "base_xp": 150,
  "adjusted_xp": 300,
  "difficulty": "easy",
  "monster_count": 3,
  "recommendation": "safe warm-up"
}
```

## Loot Parcel

`POST /v1/dm/loot-parcel`

Request:

```json
{"campaign_id": "camp-1", "tier": 1, "seed": 42}
```

For this benchmark, return deterministic tier-1 loot.

Response:

```json
{
  "campaign_id": "camp-1",
  "coins_gp": 75,
  "items": [{"slug": "healing-potion", "quantity": 2}]
}
```

## Session Recap

`POST /v1/dm/session-recap`

Request:

```json
{"campaign_id": "camp-1"}
```

Response:

```json
{
  "campaign_id": "camp-1",
  "summary": "Nyx scouts the goblin trail.",
  "open_threads": ["Resolve goblin trail ambush"]
}
```



            Previous deterministic failure report:

            ```text
            agent exited with code 1

setup or agent failed
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.


        Finish when ./run.sh is ready.
```
