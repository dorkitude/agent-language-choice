```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: 056-consumables
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

        # 056 Consumables

This cumulative suite inherits `055-equipment-and-attunement`.

Preserve all earlier behavior, including the 054 inventory stack and 055
equipment/attunement contracts. Add owner-controlled consumption for declared
consumable inventory items.

`POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume`
has no request body. Only the character owner may consume a held item.

Only `healing-potion` is consumable. Valid catalog items that are not
consumable, including `torch`, `leather-armor`, `ring-of-protection`, and
`amulet-of-health`, return 400. Unknown item IDs also return 400.

If the character has no held stack for `healing-potion`, or the held stack has
quantity zero, the request returns 409.

A valid healing potion consumption decrements exactly one stack unit and returns
200:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity_consumed":1,"total_quantity":0,"effect":{"type":"healing","hp_restored":5}}`.

When consumption reduces a stack to zero, subsequent
`GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items` must no
longer list that item.



        Finish when ./run.sh is ready.
```
