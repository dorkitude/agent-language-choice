```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: 094-safety-boundaries
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
        Use Ruby 4.0.5 and Rails 8.1.3. A minimal Rails API app is acceptable; implement the REST endpoints in Rails routes/controllers.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 094 Safety Boundaries

This cumulative suite inherits `093-moderation-workflow`.

Preserve all earlier behavior. Add campaign-scoped safety boundaries and
accepted safety events. All endpoints use `Authorization: Bearer
session-<username>`. Unauthenticated requests return 401. Unknown campaigns
return 404. Non-member users return 403. The campaign DM is considered a
campaign member for reads and safety checks.

## Replace Safety Boundaries

`PUT /v1/play/campaigns/{id}/safety-boundaries`

The request body is:

`{"blocked_tags":["gore","spiders"]}`

Only the campaign DM may replace boundaries. Players receive 403.
`blocked_tags` is required and must be a nonempty array of unique nonempty
strings. Missing, empty, non-string, blank/empty string, or duplicate tags
return 400.

Replacement is atomic: invalid requests must not mutate the previous boundary
state. Success returns 200 with the exact full current state, with tags sorted
lexicographically:

`{"blocked_tags":["gore","spiders"]}`

## Read Safety Boundaries

`GET /v1/play/campaigns/{id}/safety-boundaries`

Authenticated campaign members, including the DM, may read the exact current
boundary state:

`{"blocked_tags":["gore","spiders"]}`

The response must match the last successful replacement and keep
lexicographic order.

## Submit Safety Check

`POST /v1/play/campaigns/{id}/safety-checks`

The request body is:

`{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"]}`

Any authenticated campaign member, including the DM, may submit a safety
check. `event_id` and `text` must be nonempty strings. `kind` must be exactly
`narration` or `chat`. `tags` is required and must be a nonempty array of
unique nonempty strings. Missing or invalid fields return 400.

If `event_id` was already accepted in this campaign, return 409 and do not
append or mutate events. If any submitted tag is present in the current
`blocked_tags`, return 409 and do not append or mutate events.

Accepted checks append one event and return 201 with exactly:

`{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"],"sequence":1}`

`sequence` is the accepted safety event append order, starting at 1. The
response keeps the submitted tag order.

## Read Safety Events

`GET /v1/play/campaigns/{id}/safety-events`

Authenticated campaign members, including the DM, may read accepted safety
events. Events are returned in stable append order:

`{"events":[{"event_id":"safe-1","kind":"narration","text":"The party enters a quiet hall.","tags":["calm","exploration"],"sequence":1}]}`

Rejected blocked-tag checks, duplicate event IDs, and invalid requests must
not appear in this list.



        Finish when ./run.sh is ready.
```
