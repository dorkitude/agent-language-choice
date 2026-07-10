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

