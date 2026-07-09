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

