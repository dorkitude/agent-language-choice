```text
You are participating in a staged programming-language benchmark.

        Target: python-stdlib
        Language: python
        Framework/runtime: stdlib
        Lifecycle stage: core
        Shot kind: creative

        Create the first implementation from the seeded starter files.

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
        Use Python 3.14.6 standard library only, such as http.server and json.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Core D&D REST Engine Challenge

Build a REST API server that implements the following endpoints. All request
and response bodies are JSON unless otherwise stated.

## `GET /health`

Returns:

```json
{"ok": true}
```

## `POST /v1/dice/stats`

Request:

```json
{"expression": "2d6+3"}
```

Supported expression grammar:

```text
<count>d<sides>[+<modifier>|-<modifier>]
```

Rules:

- `count`, `sides`, and `modifier` are base-10 integers.
- `count` and `sides` must be positive.
- The modifier is optional and defaults to zero.
- Invalid expressions return HTTP 400.

Response fields:

```json
{
  "dice_count": 2,
  "sides": 6,
  "modifier": 3,
  "min": 5,
  "max": 15,
  "average": 10
}
```

## `POST /v1/checks/ability`

Request:

```json
{"roll": 9, "modifier": 5, "dc": 15}
```

Rules:

- `total = roll + modifier`
- `success = total >= dc`
- `margin = total - dc`

Response:

```json
{"total": 14, "success": false, "margin": -1}
```

## `POST /v1/encounters/adjusted-xp`

Request:

```json
{
  "party": [{"level": 3}, {"level": 3}, {"level": 3}, {"level": 3}],
  "monsters": [{"cr": "1", "count": 2}, {"cr": "2", "count": 1}]
}
```

For the first benchmark suite, support these challenge ratings:

| CR | XP |
|---|---:|
| `0` | 10 |
| `1/8` | 25 |
| `1/4` | 50 |
| `1/2` | 100 |
| `1` | 200 |
| `2` | 450 |
| `3` | 700 |
| `4` | 1100 |
| `5` | 1800 |

Monster count multipliers:

| Monster count | Multiplier |
|---:|---:|
| 1 | 1 |
| 2 | 1.5 |
| 3-6 | 2 |
| 7-10 | 2.5 |
| 11-14 | 3 |
| 15+ | 4 |

For the first benchmark suite, support level-3 encounter thresholds:

| Level | Easy | Medium | Hard | Deadly |
|---:|---:|---:|---:|---:|
| 3 | 75 | 150 | 225 | 400 |

Rules:

- `base_xp = sum(monster_xp[cr] * count)`
- `monster_count = sum(count)`
- `adjusted_xp = base_xp * multiplier`
- Party thresholds are summed across party members.
- Difficulty is the highest threshold reached: `trivial`, `easy`, `medium`,
  `hard`, or `deadly`.

Response for the sample request:

```json
{
  "base_xp": 850,
  "monster_count": 3,
  "multiplier": 2,
  "adjusted_xp": 1700,
  "difficulty": "deadly",
  "thresholds": {"easy": 300, "medium": 600, "hard": 900, "deadly": 1600}
}
```

## `POST /v1/initiative/order`

Request:

```json
{
  "combatants": [
    {"name": "rogue", "dex": 3, "roll": 14},
    {"name": "ogre", "dex": -1, "roll": 16}
  ]
}
```

Rules:

- `score = roll + dex`
- Sort by score descending.
- Break ties by dex descending.
- Break remaining ties by name ascending.

Response:

```json
{
  "order": [
    {"name": "rogue", "score": 17},
    {"name": "ogre", "score": 15}
  ]
}
```




        Finish when ./run.sh is ready.
```
