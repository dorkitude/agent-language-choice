# Refactoring Checkpoint 10: Codebase Foundation

This is a refactoring-only checkpoint. Preserve every behavior required by the
previous `dm-tools` cumulative suite. Do not add, remove, or change HTTP
endpoints, response bodies, status codes, persistence semantics, or validation
rules.

Use this session to improve the inherited implementation where it is genuinely
helpful: remove duplication, clarify module and data-flow boundaries, improve
names, add concise comments for non-obvious invariants, and correct stale or
misleading documentation. Keep the implementation deterministic and avoid
unrelated rewrites.

Create `CODEBASE.md` at the project root. It must describe the current
implementation, including:

- how to start and verify the server;
- the entry point and major modules/files;
- state, persistence, and request-routing design;
- the main API/domain groupings; and
- conventions for safely extending and testing the codebase.

The document must describe the implementation that remains after this
checkpoint, not an aspirational design.
