# Maintenance Stage 44: Encounter Rewards

Preserve all earlier behavior. The owner awards deterministic XP and loot when
closing an encounter.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/rewards` accepts
`{"xp":150,"loot":[{"slug":"healing-potion","quantity":2}]}`. Only the owner may
award rewards. Return 200 with the reward record. Rewards may be awarded only once
per encounter; duplicates return 409.

`POST /v1/play/campaigns/{id}/encounters/{enc_id}/close` marks the encounter
`closed`. Only the owner may call it. Return 200 with
`{"id":"enc-road","status":"closed","xp_awarded":150}`. Closing before awarding
rewards is allowed but returns `xp_awarded: 0`.
