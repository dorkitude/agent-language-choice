```text
You are participating in a staged programming-language benchmark.

        Target: python-django
        Language: python
        Framework/runtime: django
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
        Use Python 3.14.6 and Django 6.0.7. Implement the REST API as Django URL routes/views inside the seeded minimal project.

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
            suite=dm-tools base_url=http://127.0.0.1:54350 passed=false tests=39/40
PASS	health	1ms	HTTP 200
PASS	dice-stats-2d6-plus-3	0ms	HTTP 200
PASS	dice-stats-1d20-minus-1	0ms	HTTP 200
PASS	dice-stats-invalid	0ms	HTTP 400
PASS	ability-check-failure	0ms	HTTP 200
PASS	ability-check-success	0ms	HTTP 200
PASS	encounter-adjusted-xp	0ms	HTTP 200
PASS	initiative-order	0ms	HTTP 200
PASS	ability-modifier-negative	0ms	HTTP 200
PASS	ability-modifier-high	0ms	HTTP 200
PASS	ability-modifier-invalid	0ms	HTTP 400
PASS	proficiency-level-boundary	0ms	HTTP 200
PASS	derived-stats	0ms	HTTP 200
PASS	combat-create-session	4ms	HTTP 200
PASS	combat-add-condition	4ms	HTTP 200
PASS	combat-advance-to-mage	4ms	HTTP 200
PASS	combat-advance-to-fighter-decrements	4ms	HTTP 200
PASS	combat-advance-wrap-round	3ms	HTTP 200
PASS	combat-advance-condition-expires	3ms	HTTP 200
PASS	combat-advance-expired-removed	3ms	HTTP 200
PASS	auth-register-user	152ms	HTTP 201
PASS	auth-register-duplicate	1ms	HTTP 409
PASS	auth-login-user	150ms	HTTP 200
PASS	auth-login-bad-password	151ms	HTTP 401
PASS	storage-status	0ms	HTTP 200
PASS	storage-reset	8ms	HTTP 200
PASS	compendium-create-monster	1ms	HTTP 201
PASS	compendium-get-monster	0ms	HTTP 200
PASS	compendium-create-item	1ms	HTTP 201
PASS	compendium-get-item	0ms	HTTP 200
PASS	campaign-create	1ms	HTTP 201
PASS	campaign-add-character	1ms	HTTP 201
PASS	campaign-add-event	9ms	HTTP 201
PASS	campaign-state-read	1ms	HTTP 200
PASS	phb-spell-slots-wizard-5	0ms	HTTP 200
PASS	phb-long-rest	0ms	HTTP 200
PASS	phb-equipment-load	0ms	HTTP 200
PASS	dm-encounter-builder	0ms	HTTP 200
PASS	dm-loot-parcel	0ms	HTTP 200
FAIL	dm-session-recap	0ms	HTTP 200	open_threads: array length 0, want 1
  response: {"campaign_id": "camp-1", "summary": "Nyx scouts the goblin trail.", "open_threads": []}


Error: suite failed: 39/40 tests passed
Usage:
  dndeval run [flags]

Flags:
      --base-url string   Target server base URL (default "http://127.0.0.1:8080")
      --fail-fast         Stop at first failed test
  -h, --help              help for run
      --json-out string   Write JSON report to this path
      --suite string      Suite ID (default "core")
      --timeout string    Per-request timeout (default "3s")
  -v, --verbose           Show response details for passed tests



failed test IDs: dm-session-recap
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.


        Finish when ./run.sh is ready.
```
