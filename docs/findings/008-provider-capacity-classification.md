# Provider capacity failures preserve the retry budget

September 9, 2026. Operational tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Source context: the user requested completion of the full 5-model, 17-target, 100-stage matrix in its existing records. Infrastructure failures must not be interpreted as model capability failures or consume the original five-fix-shot budget.

GPT/Python stdlib run `20260806T132902Z_codex_gpt-5.6-terra_python-stdlib`, shot 111 (stage 90, attempt 1), exited with explicit Codex error events: “Selected model is at capacity. Please try a different model.” The old classifier stored `agent_error` and the already-running queue proceeded to attempt 2.

The exact expired-OAuth message observed in Claude preflights is also recognized as `auth_error`, preventing authentication failures from consuming model attempts.

The harness now recognizes that explicit provider error as `provider_capacity`, an infrastructure class. It continues to inspect structured error events rather than arbitrary model text. A terminal stage whose budget was shortened by a newly recognized infrastructure failure becomes resumable for its unused valid attempt; an ordinary exhausted feature failure remains terminal.

Five instrument regression tests pass, including provider capacity versus quoted agent content and five valid attempts plus one reclassified infrastructure attempt versus six valid attempts. The actual shot-111 transcript was also checked: stored `agent_error`, corrected inference `provider_capacity`.

Existing runners retain their loaded code and were not interrupted. Reconcile their database rows with the corrected classifier after they stop and run a fresh queue sweep for any unused attempts. This fix does not change generated benchmark implementations or claim the matrix is complete.
