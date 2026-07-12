# Maintenance Stage 11: Inventory And Equipment

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add campaign inventory and equipment assignment APIs.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Add Inventory Item

`POST /v1/campaigns/{id}/inventory`

Request:

```json
{"item_slug": "healing-potion", "quantity": 3, "owner": "party"}
```

Response:

```json
{"item_slug": "healing-potion", "quantity": 3, "owner": "party"}
```

## Assign Equipment

`POST /v1/campaigns/{id}/characters/{character_id}/equipment`

Request:

```json
{"item_slug": "healing-potion", "quantity": 1}
```

Response:

```json
{"character_id": "char-1", "item_slug": "healing-potion", "quantity": 1}
```

## Inventory Summary

`GET /v1/campaigns/{id}/inventory/summary`

Response:

```json
{
  "campaign_id": "camp-1",
  "party_items": 1,
  "assigned_items": 1,
  "healing_potions_available": 2
}
```
