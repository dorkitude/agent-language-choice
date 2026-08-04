```text
You are participating in a staged programming-language benchmark.

        Target: python-django
        Language: python
        Framework/runtime: django
        Lifecycle stage: 076-campaign-invitations
        Shot kind: bugfix

        You are a fresh bug-fix agent inheriting this existing codebase after a deterministic evaluator failure.

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
        Use Python 3.14.6 and Django 6.0.7. Implement the REST API as Django URL routes/views inside the seeded minimal project.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # 076 Campaign Invitations

This cumulative suite inherits `075-privacy-controls`.

Preserve all earlier behavior. Add campaign invitations so a campaign DM can
invite a registered player identity, and only that identity can accept the
invitation.

All endpoints use `Authorization: Bearer session-<username>`. Unauthenticated
requests return 401. Unknown campaigns return 404.

An invitation object is exactly:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b","status":"pending"}`

`invitation_id`, `username`, and `character_id` must be nonempty strings.
Invitation IDs are unique per campaign. A campaign cannot have more than one
active `pending` invitation for the same target username. The target username
must be a registered user with role `player`.

## Create Invitation

`POST /v1/play/campaigns/{id}/invitations`

Only the campaign DM may create invitations. The deterministic request body is:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b"}`

Success returns 201 and the exact pending invitation object. Invalid payloads or
unknown/non-player target users return 400. Duplicate invitation IDs and
duplicate active invitations for the same user return 409.

## Accept Invitation

`POST /v1/play/campaigns/{id}/invitations/{invitation_id}/accept`

Only the invited target user may accept. Other campaign members and the campaign
DM receive 403. Unknown invitation IDs return 404. Repeating acceptance returns
409.

On first acceptance, the campaign member is added using the invitation's
`character_id`, and the invitation status changes to `accepted`. Success returns
200 and the exact accepted invitation object:

`{"invitation_id":"invite-player-b","username":"player-b","character_id":"play-char-b","status":"accepted"}`

## List Invitations

`GET /v1/play/campaigns/{id}/invitations`

Returns `{"invitations":[...]}` in creation order. The campaign DM sees all
invitations. A target user sees only their own invitations, including before
they become a campaign member. Other campaign members see an empty list.



The previous evaluator attempt did not pass. Before editing, inspect
`evaluations/076-04.json` and the raw logs it references. Fix the
implementation so the same evaluator suite passes without removing
previously implemented behavior.


        Finish when ./run.sh is ready.
```
