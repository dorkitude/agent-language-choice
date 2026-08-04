```text
You are participating in a staged programming-language benchmark.

        Target: typescript-vite
        Language: typescript
        Framework/runtime: vite
        Lifecycle stage: 100-capstone-campaign-replay
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

        # 100 Capstone Campaign Replay

This final cumulative suite inherits `099-load-safe-event-feed`. Do not add
future-ticket behavior.

Use the existing authenticated REST endpoints to prove one complete deterministic
campaign replay path. Add reference-server code only if an endpoint required by
the established contracts is missing.

All authenticated play endpoints use `Authorization: Bearer session-<username>`.
Missing authentication returns `401`. Authenticated users without the required
campaign membership or role return `403` when the operation is role-forbidden;
turn-authority conflicts return `409`.

## Required Capstone Flow

The evaluator performs sequential REST calls against a fresh campaign with ID
`play-100`.

1. The DM creates the campaign and two deterministic players join it.
2. The DM starts the campaign.
3. The DM narrates the opening turn.
4. The active player submits an authenticated action and the DM resolves it.
5. The DM creates a minimal combat encounter, adds one monster, and ends combat.
6. The DM writes a campaign document containing public `story` and private
   `dm_notes`; the player document response must be exact JSON containing only
   the public `story`.
7. The DM creates and reads a versioned export snapshot.
8. Campaign members append a deterministic replay stream and both `/replay` and
   `/replay/check` must return exact identical state.
9. Campaign members append and retrieve a load-safe event feed page, including an
   append after the first page read.
10. The final terminal state check reads `/turn` and requires the exact
    exploration state with DM as current actor.

## Explicit Protection Checks

The suite asserts at least these protections in the capstone campaign:

- Unauthenticated campaign start is rejected.
- A player cannot start the campaign.
- A player cannot perform a DM narration mutation.
- The DM cannot perform the active player's action mutation.
- A player cannot resolve the DM turn.
- A player cannot update private DM document notes.
- A player cannot create a versioned export.

## Exact Terminal State

After combat ends and all document, export, replay, and feed operations complete,
`GET /v1/play/campaigns/play-100/turn` must return exact JSON:

```json
{"campaign_id":"play-100","current_actor":"dm","phase":"exploration","turn_number":2,"queue":["player-a","dm","player-b","dm"],"overdue":false,"logical_deadline":3}
```



        Finish when ./run.sh is ready.
```
