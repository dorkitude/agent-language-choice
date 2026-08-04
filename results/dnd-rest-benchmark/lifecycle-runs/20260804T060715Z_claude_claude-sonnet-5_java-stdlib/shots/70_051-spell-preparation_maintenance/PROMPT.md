```text
You are participating in a staged programming-language benchmark.

        Target: java-stdlib
        Language: java
        Framework/runtime: stdlib
        Lifecycle stage: 051-spell-preparation
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
        Use OpenJDK 26.0.1 and only the Java standard library, such as com.sun.net.httpserver.HttpServer.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 51: Spell Preparation

Preserve all earlier behavior. Add, update, and read a character's prepared
spells.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells` accepts
`{"spell_ids":["fire-bolt"]}`.
Only the character owner may call it. Return 200 if the character is a
spellcasting class, knows the spell, and the list length does not exceed the
class level's maximum prepared spells; at level 1 a wizard may prepare at most
one spell. Return
`{"character_id":"play-char-w","prepared_spells":["fire-bolt"],"max_prepared":1}`.

Return 400 for a rogue, an unknown spell, or a prepared list that exceeds the
maximum allowed count.

Return 403 if the caller is not the character owner.

`GET /v1/play/campaigns/{id}/characters/{character_id}/prepared-spells` is
allowed for any campaign member and returns the same prepared-spells response.
An empty prepared list is represented as `[]`, never omitted or `null`.



        Finish when ./run.sh is ready.
```
