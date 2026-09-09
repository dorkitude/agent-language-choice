# Failed local tools are not provider failures

September 9, 2026. Operational tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Source context: finish the full benchmark in its existing records and preserve model retry budgets when the instrument fails.

Kimi/PHP stdlib shot 122, stage 87 attempt 2, exited successfully after its local rate-limit test. Pi emitted a `tool_execution_end` event with `isError: true` because that shell command ended with code 143. The tool output included the expected benchmark HTTP 429 response. The harness mistook this local tool error for a provider rate limit and skipped evaluation.

The structured-error collector now excludes local tool events before inspecting error flags. It continues to recognize genuine provider error events. All six instrument regression tests pass, including local-tool HTTP 429 versus an explicit provider 429 error.

An isolated unchanged snapshot passed 690/690 checks with the corrected harness. The original run now has 87 completed stages and retains all 122 model shots. The effective agent classification and evaluation were corrected; original values, a compressed before-state, the archived evaluation, and the full recheck receipt remain available. A dashboard operator event discloses the correction. No model invocation or source edit was added.

The existing terminal runner already moved to Kimi/Python stdlib. A fresh sweep with the corrected code must resume PHP at stage 88 after the current queue finishes. The whole experiment remains incomplete.
