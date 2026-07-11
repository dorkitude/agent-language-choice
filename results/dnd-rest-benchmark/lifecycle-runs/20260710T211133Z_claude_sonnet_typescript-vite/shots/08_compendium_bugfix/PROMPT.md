```text
You are participating in a staged programming-language benchmark.

        Target: typescript-vite
        Language: typescript
        Framework/runtime: vite
        Lifecycle stage: compendium
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

        # Maintenance Stage 5: Monster and Item Compendium

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add SQLite-backed game-world compendium APIs for monsters and
items.

All success responses must be JSON. Invalid requests must return a non-2xx
status, preferably `400` for malformed input, `404` for unknown records, and
`409` for duplicate slugs.

## Create Monster

`POST /v1/compendium/monsters`

Request:

```json
{
  "slug": "goblin",
  "name": "Goblin",
  "cr": "1/4",
  "armor_class": 15,
  "hit_points": 7,
  "tags": ["humanoid", "goblinoid"]
}
```

Response:

```json
{
  "slug": "goblin",
  "name": "Goblin",
  "cr": "1/4",
  "armor_class": 15,
  "hit_points": 7
}
```

## Read Monster

`GET /v1/compendium/monsters/goblin`

Response:

```json
{
  "slug": "goblin",
  "name": "Goblin",
  "cr": "1/4",
  "armor_class": 15,
  "hit_points": 7,
  "tags": ["humanoid", "goblinoid"]
}
```

## Create Item

`POST /v1/compendium/items`

Request:

```json
{
  "slug": "healing-potion",
  "name": "Potion of Healing",
  "type": "potion",
  "rarity": "common",
  "cost_gp": 50
}
```

Response:

```json
{
  "slug": "healing-potion",
  "name": "Potion of Healing",
  "type": "potion",
  "rarity": "common",
  "cost_gp": 50
}
```

## Read Item

`GET /v1/compendium/items/healing-potion`

Response:

```json
{
  "slug": "healing-potion",
  "name": "Potion of Healing",
  "type": "potion",
  "rarity": "common",
  "cost_gp": 50
}
```




            Previous deterministic failure report:

            ```text
            suite=compendium base_url=http://127.0.0.1:58079 passed=false tests=28/30
PASS	health	0ms	HTTP 200
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
PASS	combat-create-session	1ms	HTTP 200
PASS	combat-add-condition	0ms	HTTP 200
PASS	combat-advance-to-mage	0ms	HTTP 200
PASS	combat-advance-to-fighter-decrements	0ms	HTTP 200
PASS	combat-advance-wrap-round	0ms	HTTP 200
PASS	combat-advance-condition-expires	0ms	HTTP 200
PASS	combat-advance-expired-removed	1ms	HTTP 200
PASS	auth-register-user	28ms	HTTP 201
PASS	auth-register-duplicate	0ms	HTTP 409
PASS	auth-login-user	21ms	HTTP 200
PASS	auth-login-bad-password	22ms	HTTP 401
PASS	storage-status	0ms	HTTP 200
PASS	storage-reset	3ms	HTTP 200
FAIL	compendium-create-monster	0ms	HTTP 200	status 200, want 201
  response: {"slug":"goblin","name":"Goblin","cr":"1/4","armor_class":15,"hit_points":7}
PASS	compendium-get-monster	0ms	HTTP 200
FAIL	compendium-create-item	0ms	HTTP 200	status 200, want 201
  response: {"slug":"healing-potion","name":"Potion of Healing","type":"potion","rarity":"common","cost_gp":50}
PASS	compendium-get-item	0ms	HTTP 200


Error: suite failed: 28/30 tests passed
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



failed test IDs: compendium-create-monster, compendium-create-item
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.


        Finish when ./run.sh is ready.
```
