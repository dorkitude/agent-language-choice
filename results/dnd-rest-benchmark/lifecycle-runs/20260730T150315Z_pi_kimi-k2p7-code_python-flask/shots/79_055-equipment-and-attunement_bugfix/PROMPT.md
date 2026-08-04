```text
You are participating in a staged programming-language benchmark.

        Target: python-flask
        Language: python
        Framework/runtime: flask
        Lifecycle stage: 055-equipment-and-attunement
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
        Use Python 3.14.6 and Flask 3.1.3. Implement the REST API as Flask routes.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 055 Equipment and Attunement

Preserve all earlier behavior, including the 054 inventory item stack contract.
Extend the inventory catalog with `leather-armor`, `ring-of-protection`, and
`amulet-of-health`; `POST /v1/play/campaigns/{id}/characters/{character_id}/inventory/items`
may add those item IDs using the same owner and quantity rules as 054.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}`
accepts `{"item_id":"leather-armor"}`. Only the character owner may equip
items. Valid slots are `armor` and `accessory`. The item must be held in the
character inventory and must match its legal slot:

- `leather-armor`: `armor`
- `ring-of-protection`: `accessory`
- `amulet-of-health`: `accessory`

Invalid slots, unknown item IDs, unheld items, and slot mismatches return 400.

Valid equipment requests return 200:

`{"character_id":"play-char-w","slot":"armor","item_id":"leather-armor","attuned":false}`.

`GET /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}` is
allowed to any campaign member. It returns the equipped item for that slot using
the same equipment response shape. Reading a valid empty slot returns
`{"character_id":"...","slot":"armor","item_id":"","attuned":false}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune`
has no request body. Only the character owner may attune. The slot must contain
an equipped attunable accessory: `ring-of-protection` or `amulet-of-health`.
Only one item may be attuned per character. A second attunement returns 409.

Valid attunement requests return 200:

`{"character_id":"play-char-w","slot":"accessory","item_id":"ring-of-protection","attuned":true,"attunement_count":1,"max_attunements":1}`.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/056-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
