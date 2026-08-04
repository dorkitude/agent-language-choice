```text
You are participating in a staged programming-language benchmark.

        Target: python-django
        Language: python
        Framework/runtime: django
        Lifecycle stage: 040-damage-and-healing
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
        Use Python 3.14.6 and Django 6.0.7. Implement the REST API as Django URL routes/views inside the seeded minimal project.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 40: Damage and Healing

Preserve all earlier behavior. The owner applies deterministic damage and
healing to encounter combatants.

## Damage

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/damage` accepts
`{"target":"goblin-1","amount":5}`. Only the owner may call it. Return 200 with
`{"target":"goblin-1","hp_before":7,"hp_after":2,"damage":5}`. HP floors at 0.

## Healing

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/heal` accepts
`{"target":"goblin-1","amount":3}`. Only the owner may call it. Return 200 with
`{"target":"goblin-1","hp_before":2,"hp_after":5,"healing":3}`. HP caps at
`hp_max`.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/040-01.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
