```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: inventory-equipment
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
- rust: 1.97.0
- sinatra: 4.2.1
- slim: 4.15.2
- slim-psr7: 1.8.0
- symfony-http-foundation: 8.1.1
- symfony-routing: 8.1.0
- typescript: 7.0.2
- vite: 8.1.3

        Target guidance:
        Use Ruby 4.0.5 and Rails 8.1.3. A minimal Rails API app is acceptable; implement the REST endpoints in Rails routes/controllers.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

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



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/013-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
