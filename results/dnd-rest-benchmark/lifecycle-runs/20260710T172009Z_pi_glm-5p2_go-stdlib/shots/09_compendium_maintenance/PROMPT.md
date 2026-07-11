```text
You are participating in a staged programming-language benchmark.

        Target: go-stdlib
        Language: go
        Framework/runtime: stdlib
        Lifecycle stage: compendium
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




        Finish when ./run.sh is ready.
```
