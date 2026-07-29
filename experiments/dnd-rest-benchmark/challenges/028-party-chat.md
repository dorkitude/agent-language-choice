# Maintenance Stage 28: Party Chat

Any authenticated campaign member can post
`POST /v1/play/campaigns/{id}/messages` with `{"text":"..."}`. Return a
chronological `chat` event with actor/text and the unchanged `current_actor`.
Chat never advances the turn.
