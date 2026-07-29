# Maintenance Stage 30: Campaign Document

The owner updates the durable role-filtered campaign document with
`PUT /v1/play/campaigns/{id}/document` and
`{"story":"...","dm_notes":"..."}`. The owner receives both fields. A
player cannot update it (403) and `GET /v1/play/campaigns/{id}/document` for a
player returns only the public `story`; it must not disclose `dm_notes`.
