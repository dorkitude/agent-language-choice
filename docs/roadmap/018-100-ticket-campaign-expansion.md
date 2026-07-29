# Campaign Play Expansion: Tickets 017–100

Status: tickets 017–030 specified, registered in the lifecycle runner, and
covered by cumulative evaluator suites. Tickets 031–100 remain planned.

The completed dataset remains the nine-stage baseline. The runnable roadmap now
contains stages 001–030, and this document expands the post-analytics backlog
to **100 total feature tickets**: the existing 16 plus the 84 tickets below.
Keeping the extended stages out of the frozen result set preserves its
comparability while giving the next benchmark generation a concrete, testable
direction.

## Design Goal

Turn the single-campaign CRUD API into a small, agent-playable game service.
A user can authenticate as a DM or player, form a party, start a campaign, and
progress a shared narrated turn loop. The server remains the source of truth
for authorization, state, turns, and deterministic mechanics; agents provide
the prose and decisions.

The design is informed by the public AgentRPG project’s role-separated player
and GM context, campaign document, party observations, and heartbeat model.
It is an independent benchmark specification: do not copy AgentRPG source,
prose, fixtures, or API contracts into this MIT-licensed repository.

## Evaluator Contract: External Deterministic REST Only

Every ticket in this expansion is incomplete until the central `dndeval` CLI
has a cumulative suite for it. The suite must treat the implementation as an
opaque server process and exercise it **only through HTTP/JSON** at
`--base-url`; it must never inspect implementation files, call internal
functions, read a database, or depend on an agent transcript.

For each ticket `NNN-feature`, the deliverables are:

1. `challenges/NNN-feature.md` — the agent-facing HTTP contract, including
   method/path, request and response schemas, authorization, error statuses,
   ordering rules, and any deterministic seed.
2. A Go `dndeval` suite — registered as `NNN-feature` and cumulative over all
   earlier enabled tickets. It provisions preconditions through the same public
   REST endpoints a real client would use.
3. Deterministic fixtures — explicit IDs, credentials, timestamps or logical
   clocks, and RNG seeds. No wall-clock timing, random UUID, provider output,
   or network dependency may affect an assertion.
4. Black-box assertions — status codes, response JSON shape/values, event
   ordering, authorization boundaries, and persistence behavior visible after
   a server restart where the ticket requires persistence.

The acceptance command for a ticket will be:

```sh
cd experiments/dnd-rest-benchmark/evaluator
go run . run --base-url http://127.0.0.1:8080 --suite NNN-feature
```

The lifecycle harness must invoke that same CLI after the agent finishes.
This preserves the study’s central property: all language targets receive the
same externally observable contract and are scored independently of their
implementation approach.

## First Vertical Slice: Tickets 017–030

These tickets directly implement the requested DM/player campaign loop. Each
has its own challenge spec and cumulative evaluator suite and is enabled in
`LIFECYCLE_STAGES`.

| Ticket | Feature | API/evaluator focus |
| ---: | --- | --- |
| 017 | DM campaign ownership | Require an authenticated `dm` to create a campaign; reject player ownership changes. |
| 018 | Party membership | Players join/leave a campaign with one owned character; enforce capacity and duplicate rules. |
| 019 | Campaign start state | The owner starts a sufficiently populated campaign exactly once; expose `lobby`, `active`, and `completed`. |
| 020 | GM narration | Authenticated owner appends ordered narration to the campaign event log. |
| 021 | Role-based authorization | Enforce bearer `session-<username>` identity and campaign-scoped DM/player permissions. |
| 022 | Exploration turn queue | Start an ordered player/DM queue with a single authoritative active turn. |
| 023 | Player turn context | `GET /v1/campaigns/{id}/my-turn` returns only the authenticated player’s permitted context and `is_my_turn`. |
| 024 | GM turn context | `GET /v1/campaigns/{id}/gm/status` returns owner-only queue, party summary, recent events, and `needs_attention`. |
| 025 | Player action submission | An active player submits a typed action and prose; server records an immutable event and advances to GM. |
| 026 | GM resolution | The active GM narrates/resolves the preceding action and advances to the next player. |
| 027 | Turn timeout policy | Expose deterministic overdue state; owner can nudge or apply a documented default/skip. |
| 028 | Party chat | Members post chronological in-character messages without advancing the turn. |
| 029 | Party observations | Members record attributed, append-only world/party/self observations. |
| 030 | Campaign document | Maintain a compact public story summary plus DM-private notes; filter each response by role. |

### Vertical-slice contract

New endpoints build on the existing `/v1/auth/*` and `/v1/campaigns/*` routes.
All protected calls use `Authorization: Bearer session-<username>`. A production
implementation must validate a real session; deterministic tokens are retained
only to make the benchmark cross-language and reproducible.

The central cumulative evaluator should establish this exact flow:

1. Register `dm` and two `player` users; log each in.
2. Have the authenticated DM create campaign `camp-1`; have each player add an
   owned character and join the party.
3. Start the campaign; verify that no player can narrate, resolve, or read
   DM-private notes, and that no unrelated player can read the campaign.
4. Verify player A receives `is_my_turn: true`, submits an action, and sees it
   in the event log.
5. Verify the DM receives `needs_attention: true`, narrates a resolution, and
   advances the queue to player B.
6. Verify role-filtered context, ordered events, and preserved prior API
   behavior after a process restart where the current suite requires storage.

## Remaining Tickets

The rest of the expansion is intentionally decomposed into small maintenance
steps. A future batch should add challenge files and evaluator suites in order;
do not activate a partially specified batch.

| Ticket | Feature | Evaluator focus |
| ---: | --- | --- |
| 031 | Scene state | Create, enter, and close scenes with a current-scene pointer. |
| 032 | Location graph | Deterministic locations and valid travel edges. |
| 033 | Travel turns | Party travel consumes a turn and records a destination event. |
| 034 | Rest turns | Short/long rest eligibility, resource reset, and event logging. |
| 035 | Encounter creation | DM starts a campaign-bound encounter from party and monster state. |
| 036 | Monster roster | DM adds/removes deterministic monster combatants. |
| 037 | Party/combat binding | Campaign characters enter/leave the active encounter correctly. |
| 038 | Combat turn authority | Only the current combatant or DM can advance/resolve the relevant turn. |
| 039 | Player combat actions | Attack, help, dodge, and ready action validation and event output. |
| 040 | Damage and healing | Deterministic HP bounds, damage, healing, and audit events. |
| 041 | Death saves | Stable success/failure counters and unconscious/dead state transitions. |
| 042 | Condition interactions | Apply, expire, and serialize multiple named conditions. |
| 043 | Delay and ready | Reorder legal initiative turns without duplication. |
| 044 | Encounter rewards | Award deterministic XP and loot on encounter close. |
| 045 | Combat/exploration transition | Return the campaign queue to exploration after combat ends. |
| 046 | Character ownership | Link a character to exactly one player identity per campaign. |
| 047 | Character creation choices | Validate race/class/background choices and derived defaults. |
| 048 | Level progression | Apply deterministic level-up thresholds and class resources. |
| 049 | Skills and proficiencies | Resolve valid proficiency and skill-check modifiers. |
| 050 | Spellbook state | Add, list, and validate known spells against character class. |
| 051 | Spell preparation | Enforce preparation limits and idempotent prepared lists. |
| 052 | Spell casting | Consume slots and emit deterministic spell-cast events. |
| 053 | Concentration | Replace/clear concentration and apply turn-based expiry. |
| 054 | Inventory stacks | Add, remove, and reject invalid item quantities. |
| 055 | Equipment and attunement | Equip legal items and enforce attunement limits. |
| 056 | Consumables | Consume an item exactly once and apply its declared effect. |
| 057 | Currency and trade | Atomic transfers with non-negative balances. |
| 058 | Loot distribution | Party vote/assignment outcomes with an immutable record. |
| 059 | NPC agendas | DM-managed NPC goals and visible/public status fields. |
| 060 | Faction reputation | Bounded reputation changes and role-filtered history. |
| 061 | NPC dialogue | Append attributed dialogue and reveal only public text. |
| 062 | Relationship graph | Create/update bounded relationship edges among campaign entities. |
| 063 | Secrets and clues | DM reveals a clue to one player, party, or nobody. |
| 064 | Quest dependencies | Gate quest state transitions on deterministic prerequisites. |
| 065 | Quest rewards | Award configured XP/items only once on completion. |
| 066 | World events | Schedule and resolve a campaign-level event in turn order. |
| 067 | Rumors | Publish, discover, and deduplicate rumor records. |
| 068 | Calendar and weather | Advance campaign time and deterministically derive weather. |
| 069 | Settlements | Manage settlement services, availability, and campaign discovery. |
| 070 | Shops | Browse stock and buy/sell through inventory and currency APIs. |
| 071 | Recipe catalog | Add deterministic crafting recipes and ingredient requirements. |
| 072 | Recurring downtime | Allocate, progress, and complete repeated downtime activities. |
| 073 | Session-zero settings | Persist campaign rules, tone, and consent settings before start. |
| 074 | Content tags | Tag scenes/events and filter role-appropriate content. |
| 075 | Privacy controls | Restrict private notes, whispers, and character sheets by role. |
| 076 | Campaign invitations | DM invites a player; only the invited identity can accept. |
| 077 | GM delegation | Owner grants/revokes limited co-GM authority with audit entries. |
| 078 | Actor audit trail | Every mutating event has actor, role, timestamp, and correlation ID. |
| 079 | Event projections | Rebuild campaign state from an ordered event log. |
| 080 | Idempotency keys | Duplicate mutating requests with the same key have one effect. |
| 081 | Concurrent turn safety | Reject stale turn submissions without corrupting queue state. |
| 082 | Transaction recovery | Failed compound mutations leave no partial state. |
| 083 | Versioned export | Export a canonical, versioned campaign snapshot. |
| 084 | Import validation | Import only valid compatible snapshots; reject malformed data. |
| 085 | Schema migration | Migrate an older exported snapshot deterministically. |
| 086 | Pagination/search | Stable pagination, filtering, and ordering for logs and entities. |
| 087 | Rate limits | Per-identity request limits with deterministic retry metadata. |
| 088 | Service metrics | Aggregate safe counters without leaking campaign content. |
| 089 | Readiness/health | Separate liveness, readiness, and storage health responses. |
| 090 | Backup and restore | Restore a backup without duplicating event identities. |
| 091 | Deterministic replay | Replay a seeded campaign history to the same public state. |
| 092 | Deterministic RNG ledger | Store seed/roll provenance and prevent untracked random outcomes. |
| 093 | Moderation workflow | Report, review, and resolve a message/event with role controls. |
| 094 | Safety boundaries | Enforce campaign content settings on narration and chat tags. |
| 095 | Fixture seeding | Create an idempotent canonical campaign fixture for evaluators. |
| 096 | API schema endpoint | Serve a versioned machine-readable API/schema summary. |
| 097 | Agent onboarding | Return authenticated, role-specific next-step instructions. |
| 098 | Spectator view | Provide a deliberately redacted public campaign projection. |
| 099 | Load-safe event feed | Cursor-based event feed with stable ordering under writes. |
| 100 | Capstone campaign replay | Full authenticated DM/player campaign: lobby, start, narrated turns, combat, persistence, export, and deterministic replay. |

## Rollout Rule

The 100-ticket plan is a product-scale benchmark, not a single immediate
matrix. Implement and validate it in batches (017–030, 031–045, and so on),
freeze each batch, then decide whether the full 100-stage lifecycle is
affordable and methodologically appropriate. The primary research result must
continue to identify the exact stage range used.
