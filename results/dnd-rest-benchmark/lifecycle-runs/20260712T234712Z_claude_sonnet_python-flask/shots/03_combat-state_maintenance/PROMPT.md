```text
You are participating in a staged programming-language benchmark.

        Target: python-flask
        Language: python
        Framework/runtime: flask
        Lifecycle stage: combat-state
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

        # Maintenance Stage 2: Stateful Combat

You are inheriting an existing D&D REST API codebase. Preserve every endpoint
from the core and character-rule suites and add the endpoints below.

All state may be in memory. State only needs to last for the lifetime of the
server process.

All success responses must be JSON. Invalid requests must return a non-2xx
status, preferably `400` for malformed input and `404` for unknown session IDs.

## Create Combat Session

`POST /v1/combat/sessions`

Request:

```json
{
  "id": "enc-1",
  "combatants": [
    {"name": "fighter", "dex": 1, "roll": 13},
    {"name": "rogue", "dex": 3, "roll": 14},
    {"name": "mage", "dex": 2, "roll": 14}
  ]
}
```

Rules:

- `id` is client-supplied and must uniquely identify the session.
- Initiative score is `roll + dex`.
- Sort initiative by score descending, then dex descending, then name ascending.
- New sessions start at `round = 1` and `turn_index = 0`.
- `active` is the combatant at the current `turn_index`.

Response:

```json
{
  "id": "enc-1",
  "round": 1,
  "turn_index": 0,
  "active": {"name": "rogue", "score": 17},
  "order": [
    {"name": "rogue", "score": 17},
    {"name": "mage", "score": 16},
    {"name": "fighter", "score": 14}
  ]
}
```

## Add Condition

`POST /v1/combat/sessions/{id}/conditions`

Request:

```json
{
  "target": "fighter",
  "condition": "blessed",
  "duration_rounds": 2
}
```

Rules:

- `target` must name a combatant in the session.
- `condition` is an arbitrary string.
- `duration_rounds` must be a positive integer.
- Conditions are attached to the named combatant.

Response:

```json
{
  "target": "fighter",
  "conditions": [
    {"condition": "blessed", "remaining_rounds": 2}
  ]
}
```

## Advance Turn

`POST /v1/combat/sessions/{id}/advance`

Rules:

- Advance `turn_index` to the next combatant.
- When the turn index wraps from the end of the initiative order back to `0`,
  increment `round`.
- At the start of a combatant's turn, decrement each condition attached to that
  active combatant.
- Remove a condition when its remaining duration reaches `0`.
- Conditions on inactive combatants do not decrement.

Response shape:

```json
{
  "id": "enc-1",
  "round": 1,
  "turn_index": 1,
  "active": {"name": "mage", "score": 16},
  "conditions": {
    "fighter": [
      {"condition": "blessed", "remaining_rounds": 2}
    ]
  }
}
```



        Finish when ./run.sh is ready.
```
