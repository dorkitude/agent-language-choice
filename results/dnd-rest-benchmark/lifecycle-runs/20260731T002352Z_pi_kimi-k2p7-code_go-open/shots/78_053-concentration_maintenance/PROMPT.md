```text
You are participating in a staged programming-language benchmark.

        Target: go-open
        Language: go
        Framework/runtime: open-modules
        Lifecycle stage: 053-concentration
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
        Use Go 1.26.5. Third-party Go modules are allowed and should be recorded in go.mod/go.sum. Choose idiomatic libraries where they reduce implementation risk; for real SQLite support, prefer the pure-Go modernc.org/sqlite driver (or another compatible driver) rather than requiring CGO. Runtime network access remains forbidden.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 53: Concentration

Preserve all earlier behavior. Add, read, replace, advance, and clear a
character's current concentration state.

`PUT /v1/play/campaigns/{id}/characters/{character_id}/concentration` accepts
`{"spell_id":"magic-missile","target":"training-dummy","duration_turns":2}`.
Only the character owner may call it. Return 200 if the character is a
spellcasting class, knows the spell, has it currently prepared, and the duration
is positive. The response is
`{"character_id":"play-char-w","concentration":{"spell_id":"magic-missile","target":"training-dummy","remaining_turns":2}}`.

A second valid `PUT` replaces any existing concentration for that character
instead of appending or rejecting it. The response shape is the same with the new
spell, target, and remaining turn count.

`GET /v1/play/campaigns/{id}/characters/{character_id}/concentration` is allowed
for any campaign member and returns
`{"character_id":"play-char-w","concentration":{...}}` when concentration is
active. When no concentration is active, return
`{"character_id":"play-char-w","concentration":null}`.

`POST /v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn`
is allowed for any campaign member. It decrements the active concentration's
`remaining_turns` by one and clears concentration when the count reaches zero.
Return the same shape as the read endpoint after applying the turn advance.

`DELETE /v1/play/campaigns/{id}/characters/{character_id}/concentration` is
allowed only for the character owner. It clears concentration and returns
`{"character_id":"play-char-w","concentration":null}`. Return 403 if the caller
is not the character owner. Return 400 if the spell is unknown, not currently
prepared, the character is not a spellcaster, or `duration_turns` is less than
one.



        Finish when ./run.sh is ready.
```
