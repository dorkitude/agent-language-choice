# Maintenance Stage 27: Turn Timeout Policy

Expose deterministic timeout metadata on the turn endpoint: `overdue:false`
for a fresh turn and a logical integer deadline. The owner can
`POST /v1/play/campaigns/{id}/turn/nudge` with a nonempty `message`; return
201 with actor, current target, message, and monotonically increasing
`nudge_count`. Do not use wall-clock time in this benchmark.
