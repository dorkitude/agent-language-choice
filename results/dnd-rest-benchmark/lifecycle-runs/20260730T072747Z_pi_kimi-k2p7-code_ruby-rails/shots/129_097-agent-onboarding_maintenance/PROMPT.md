```text
You are participating in a staged programming-language benchmark.

        Target: ruby-rails
        Language: ruby
        Framework/runtime: rails
        Lifecycle stage: 097-agent-onboarding
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

        # 097 Agent Onboarding

This cumulative suite inherits `096-api-schema-endpoint`.

Preserve all earlier behavior. Add authenticated campaign-member onboarding for
agents entering an existing campaign. Do not add later spectator behavior unless
the existing server model already has a spectator member role.

## Read Campaign Onboarding

`GET /v1/play/campaigns/{id}/onboarding`

Authentication and campaign membership are required.

- Missing or invalid `Authorization` returns 401.
- Authenticated requests for unknown campaigns return 404.
- Authenticated users who are not members of the campaign return 403.
- The campaign owner/DM and player members can read onboarding.

For the campaign owner/DM, return exactly:

`{"role":"dm","next_steps":["configure-safety","invite-players","start-campaign"],"can_mutate":true}`

For a player member, return exactly:

`{"role":"player","next_steps":["review-party","take-turn","submit-action"],"can_mutate":true}`

The response is role-specific, stable across repeated reads, and must not depend
on map iteration order or mutate campaign state.



        Finish when ./run.sh is ready.
```
