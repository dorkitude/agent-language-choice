# Server log backpressure correction

Recorded 2026-09-09. [Operational issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

The evaluator launched benchmark servers with stdout/stderr pipes but read those pipes only after the entire suite finished. Verbose servers could fill the pipe and block while writing HTTP access logs. This creates a language/framework-correlated measurement artifact. Increasing the request deadline cannot unblock an undrained pipe.

Evidence: the saved Kimi / Flask run at stage 079-event-projections failed 15 of 584 checks with client deadlines; its stderr file was 65,501 bytes. Re-evaluating the exact current implementation after redirecting stdout/stderr directly to the original server log files passed all 584 checks. Its new stderr was 67,180 bytes. No generated source changes were made for this recheck. Historical shot archives remain intact; the diagnostic report is in the local .cache/resume-20260909/flask-recheck.json.

The regression test starts a server that writes 256 KiB each to stdout and stderr before health, then another 256 KiB per request. It verifies that health and evaluation complete and logs are preserved beyond the pipe capacity.

The earlier Pi bootstrap and infrastructure retry-budget working-tree fixes are also preserved. The 30-second request deadline and serialized evaluation remain unchanged. Rerun affected timeout cells under the corrected harness before final comparisons; do not count their historical evaluator timeouts as capability failures.

Provider readiness on September 9: Fireworks live serverless catalog lists accounts/fireworks/models/kimi-k2p7-code (262144 context, $0.95/M input, $4/M output) and accounts/fireworks/models/glm-5p2 (1048576 context, $1.4/M input, $4.4/M output); no dated variants of these two appeared in the listing. Source: https://fireworks.ai/models?modelTypes=Serverless&serverless=true . Credentials are not available to the current agent session. Both Claude model preflights reported expired OAuth with refresh failure. GPT-5.6 Terra matrix resumed under PID 13427 with two workers and original five-fix-shot budget.
