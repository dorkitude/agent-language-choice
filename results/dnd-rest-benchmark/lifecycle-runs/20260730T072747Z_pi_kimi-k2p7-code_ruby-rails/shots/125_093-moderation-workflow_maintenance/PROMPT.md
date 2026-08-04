```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: 093-moderation-workflow
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

        # 093 Moderation Workflow

This cumulative suite inherits `092-rng-ledger`.

Preserve all earlier behavior. Add campaign-scoped moderation reports for
authenticated campaign members and a single DM-only resolution transition.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404. Non-member users return
403. The campaign DM is also a campaign member for report creation and reads.

## Submit Moderation Report

`POST /v1/play/campaigns/{id}/moderation/reports`

The request body is:

`{"report_id":"report-1","target_id":"event-1","reason":"spam"}`

Any authenticated campaign member, including the DM, may submit a report.
`report_id`, `target_id`, and `reason` must be nonempty strings. Missing or
empty strings return 400. `report_id` must be unique within the campaign;
duplicates return 409 and must not append or mutate any report.

Success returns 201 with the exact immutable open report record:

`{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"open","reporter":"<username>","sequence":1}`

`sequence` is the accepted report append order, starting at 1.

## Read Moderation Reports

`GET /v1/play/campaigns/{id}/moderation/reports`

Authenticated campaign members, including the DM, may read moderation reports.
Reports must be returned in stable append order:

`{"reports":[{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"open","reporter":"player-a","sequence":1}]}`

## Resolve Moderation Report

`PUT /v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution`

The request body is:

`{"action":"allow","note":"Reviewed and allowed."}`

Only the campaign DM may resolve reports. Players receive 403. Unknown reports
return 404. `action` must be exactly `allow` or `remove`, and `note` must be a
nonempty string. Missing/invalid action or empty note returns 400.

Resolving an open report returns 200 with the exact resolved record:

`{"report_id":"report-1","target_id":"event-1","reason":"spam","status":"resolved","reporter":"player-a","sequence":1,"action":"remove","note":"Removed duplicate spam event.","resolver":"dm"}`

Resolving the same report again returns 409 and must not mutate the record.
The report record is immutable except for this one transition from `open` to
`resolved`; append order and sequence values remain stable.



        Finish when ./run.sh is ready.
```
