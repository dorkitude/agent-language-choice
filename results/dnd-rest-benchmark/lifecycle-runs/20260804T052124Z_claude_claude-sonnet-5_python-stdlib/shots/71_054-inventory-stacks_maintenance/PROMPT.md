```text
You are participating in a staged programming-language benchmark.

        Target: python-stdlib
        Language: python
        Framework/runtime: stdlib
        Lifecycle stage: 054-inventory-stacks
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

        # 054 Inventory Stacks

Preserve all earlier behavior. Add per-character inventory item stacks.

`POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items`
accepts `{"item_id":"healing-potion","quantity":2}`. Only the character owner
may add items. Valid item IDs are `healing-potion` and `torch`. Quantity must be
positive. Invalid item IDs or quantities return 400.

Valid requests increment that character's item stack and return 201:

`{"character_id":"play-char-w","item_id":"healing-potion","quantity":2,"total_quantity":2}`.

`GET /v1/play/campaigns/{id}/characters/{character_id}/inventory/items` is
allowed to any campaign member and returns 200:

`{"character_id":"play-char-w","items":[{"item_id":"healing-potion","quantity":2}]}`.

Items must be returned in lexicographic `item_id` order. Characters with no
held items return `{"character_id":"...","items":[]}`.

`DELETE /v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}`
accepts `{"quantity":1}`. Only the character owner may remove items. Quantity
must be positive and no larger than the held stack. Invalid quantities or
unknown catalog items return 400. Removing more than the held quantity returns
409.

Valid removal requests decrement the stack and return 200 using the same item
response shape with the remaining `total_quantity`.



        Finish when ./run.sh is ready.
```
