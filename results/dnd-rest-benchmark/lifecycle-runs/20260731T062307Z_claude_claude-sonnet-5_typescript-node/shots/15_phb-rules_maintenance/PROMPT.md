```text
You are participating in a staged programming-language benchmark.

        Target: typescript-node
        Language: typescript
        Framework/runtime: node-stdlib
        Lifecycle stage: phb-rules
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
        Use TypeScript 7.0.2 and Node 26.4.0 built-in HTTP APIs. Do not add frameworks.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 7: Selected PHB Rules

You are inheriting an existing D&D REST API codebase. Preserve every previous
endpoint and add deterministic endpoints for selected Player's Handbook-style
rules.

All success responses must be JSON. Invalid requests must return a non-2xx
status.

## Spell Slots

`POST /v1/phb/spell-slots`

Request:

```json
{"class": "wizard", "level": 5}
```

For this benchmark, support wizard level 5.

Response:

```json
{"class": "wizard", "level": 5, "slots": {"1": 4, "2": 3, "3": 2}}
```

## Long Rest

`POST /v1/phb/rests/long`

Request:

```json
{"level": 5, "hp_current": 9, "hp_max": 35, "hit_dice_spent": 3, "exhaustion_level": 1}
```

Rules:

- Long rest restores current HP to max HP.
- Long rest restores spent hit dice up to half the character level, rounded
  down, minimum 1.
- Long rest reduces exhaustion by 1, to a minimum of 0.

Response:

```json
{"hp_current": 35, "hit_dice_spent": 1, "exhaustion_level": 0}
```

## Equipment Load

`POST /v1/phb/equipment-load`

Request:

```json
{"strength": 12, "weight": 181}
```

Rules:

- Carrying capacity is `strength * 15`.
- `encumbered` is true when carried weight exceeds capacity.

Response:

```json
{"capacity": 180, "weight": 181, "encumbered": true}
```



        Finish when ./run.sh is ready.
```
