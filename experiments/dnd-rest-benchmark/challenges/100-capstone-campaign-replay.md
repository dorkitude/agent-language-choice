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
