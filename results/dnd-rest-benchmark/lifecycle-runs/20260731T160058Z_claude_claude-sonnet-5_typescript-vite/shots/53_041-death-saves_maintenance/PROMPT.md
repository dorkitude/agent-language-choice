```text
You are participating in a staged programming-language benchmark.

        Target: typescript-vite
        Language: typescript
        Framework/runtime: vite
        Lifecycle stage: 041-death-saves
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
        Use Vite 8.1.3 with TypeScript. Implement the REST API through Vite dev-server middleware or a Vite plugin; do not replace it with a plain Node-only server.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Maintenance Stage 41: Death Saves

Preserve all earlier behavior. Track stable success/failure counters and
unconscious/dead state transitions for a character at 0 HP.

The owner may reduce a character to 0 HP with
`POST /v1/play/campaigns/{id}/characters/{char_id}/damage {"amount":20}`;
when a character's `hp_current` reaches 0, its status becomes `unconscious`.

`POST /v1/play/campaigns/{id}/characters/{char_id}/death-saves` accepts
`{"outcome":"success"}` or `{"outcome":"failure"}`. Only the character's owner
may call it. Return 201 with the updated counters:
`{"character_id":"play-char-a","successes":1,"failures":0,"status":"unconscious"}`.

Three successes make the character `stable` (no further rolls accepted). Three
failures make the character `dead`. Non-owners or rolls on a conscious
character return 403/409.

`GET /v1/play/campaigns/{id}/characters/{char_id}/status` returns
`{"character_id":"play-char-a","hp_current":0,"hp_max":20,"status":"unconscious"}`
for any campaign member.



        Finish when ./run.sh is ready.
```
