# Maintenance Stage 20: GM Narration

The campaign owner appends narration with
`POST /v1/play/campaigns/{id}/narrations` and `{"text":"..."}`. Return 201
with an ordered event: `sequence`, `kind:"narration"`, `actor:"dm"`, and
`text`. A player cannot narrate (403). Event sequence starts at 1 for each
campaign and is append-only.
