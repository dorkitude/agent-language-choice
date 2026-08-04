```text
You are participating in a staged programming-language benchmark.

        Target: php-stdlib
        Language: php
        Framework/runtime: stdlib
        Lifecycle stage: 030-codebase-refactor
        Shot kind: maintenance

        You are a fresh refactoring agent inheriting this existing codebase. Improve its internal structure and documentation while preserving all observable behavior.

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
        Use PHP 8.5.8 and the built-in PHP server. Do not add Composer packages.

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        # Refactoring Checkpoint 30: Campaign-Play Cleanup

This is a refactoring-only checkpoint. Preserve every behavior required by the
previous `030-campaign-document` cumulative suite. Do not add, remove, or
change HTTP endpoints, response bodies, status codes, persistence semantics,
or validation rules.

Use this session to improve the inherited implementation where it is genuinely
helpful: remove duplication, clarify module and data-flow boundaries, improve
names, add concise comments for non-obvious invariants, and correct stale or
misleading documentation. Keep the implementation deterministic and avoid
unrelated rewrites.

Update the root `CODEBASE.md` so it accurately covers the current codebase.
It must describe how to start and verify the server, the entry point and major
modules/files, state/persistence/request routing, the main API/domain
groupings, and conventions for safely extending and testing the codebase.



        Finish when ./run.sh is ready.
```
