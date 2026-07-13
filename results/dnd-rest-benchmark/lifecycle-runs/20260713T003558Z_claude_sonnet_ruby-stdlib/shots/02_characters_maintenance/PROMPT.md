```text
You are participating in a staged programming-language benchmark.

        Target: ruby-stdlib
        Language: ruby
        Framework/runtime: stdlib
        Lifecycle stage: characters
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

        # Maintenance Stage 1: Character Rules

You are inheriting an existing D&D REST API codebase. Preserve every endpoint
from the core suite and add the endpoints below.

All success responses must be JSON. Invalid requests must return a non-2xx
status, preferably `400`.

## Ability Modifier

`POST /v1/characters/ability-modifier`

Request:

```json
{"score": 9}
```

Rules:

- `score` must be an integer from `1` through `30`.
- `modifier = floor((score - 10) / 2)`.
- This must floor negative halves correctly: score `9` yields `-1`.

Response:

```json
{"score": 9, "modifier": -1}
```

## Proficiency Bonus

`POST /v1/characters/proficiency`

Request:

```json
{"level": 9}
```

Rules:

- `level` must be an integer from `1` through `20`.
- Levels `1-4` have bonus `2`.
- Levels `5-8` have bonus `3`.
- Levels `9-12` have bonus `4`.
- Levels `13-16` have bonus `5`.
- Levels `17-20` have bonus `6`.

Response:

```json
{"level": 9, "proficiency_bonus": 4}
```

## Derived Stats

`POST /v1/characters/derived-stats`

Request:

```json
{
  "level": 5,
  "abilities": {
    "str": 16,
    "dex": 14,
    "con": 13,
    "int": 8,
    "wis": 12,
    "cha": 10
  },
  "armor": {
    "base": 12,
    "shield": true,
    "dex_cap": 2
  }
}
```

Rules:

- Compute every ability modifier with the same formula as the standalone
  ability-modifier endpoint.
- Compute proficiency from level.
- `hp_max = level * (6 + constitution_modifier)`.
- `armor_class = armor.base + min(dex_modifier, armor.dex_cap) + shield_bonus`.
- `shield_bonus` is `2` when `armor.shield` is true, otherwise `0`.

Response:

```json
{
  "level": 5,
  "proficiency_bonus": 3,
  "hp_max": 35,
  "armor_class": 16,
  "modifiers": {
    "str": 3,
    "dex": 2,
    "con": 1,
    "int": -1,
    "wis": 1,
    "cha": 0
  }
}
```



        Finish when ./run.sh is ready.
```
