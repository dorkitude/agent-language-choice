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
