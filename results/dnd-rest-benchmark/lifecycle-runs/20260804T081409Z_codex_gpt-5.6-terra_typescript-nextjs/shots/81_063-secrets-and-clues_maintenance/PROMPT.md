```text
You are participating in a staged programming-language benchmark.

        Target: typescript-nextjs
        Language: typescript
        Framework/runtime: nextjs
        Lifecycle stage: 063-secrets-and-clues
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
        Use Next.js 16.2.10, React 19.2.7, and TypeScript 7.0.2. Implement endpoints as Next route handlers under app/.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 063 Secrets and Clues

This cumulative suite inherits `062-relationship-graph`.

Preserve all earlier behavior. Add campaign clues that the DM may reveal to one
character, the party, or nobody.

`POST /v1/play/campaigns/{id}/clues` accepts:

`{"clue_id":"clue-letter","text":"The Black Spider seeks Wave Echo Cave.","audience":"character","character_id":"play-char-w"}`.

Only the campaign DM may create clues. Players receive 403 for creation.
`clue_id` and `text` are required nonempty strings. `audience` must be exactly
`character`, `party`, or `hidden`.

For `character` audience, `character_id` is required and must name a campaign
member character. Unknown characters return 400. For `party` and `hidden`
audience, `character_id` must be omitted. Unknown or invalid audiences and
invalid audience/character combinations return 400. Clue IDs are unique per
campaign; duplicates return 409.

A valid character clue create returns 201 exactly:

`{"clue_id":"clue-letter","text":"The Black Spider seeks Wave Echo Cave.","audience":"character","character_id":"play-char-w"}`

A valid party or hidden clue create returns 201 exactly:

`{"clue_id":"clue-party","text":"The cave entrance lies east of Phandalin.","audience":"party"}`

`GET /v1/play/campaigns/{id}/clues` is available to authenticated campaign
members and returns:

`{"clues":[...]}`

The DM receives all clues in insertion order. A player receives party clues and
character clues targeted to their own character only. Hidden clues and clues
targeted to another player's character never appear in player responses. Each
returned clue uses the exact creation response shape: character clues include
`character_id`; party and hidden clues omit `character_id`.



        Finish when ./run.sh is ready.
```
