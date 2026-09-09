# Operator recovery of a hung local probe

Recorded 2026-09-09T16:46:26Z; [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Kimi / Django's current stage-77 agent had spent over27minutes awaiting one localhost POST to its own generated server. The curl command had no timeout, remained ESTABLISHED, and had used only0.05CPU seconds. An independent read-only GET /health returned200 in0.001seconds. This identified a blocked application request rather than provider latency or an unavailable backend.

The operator sent SIGTERM to the single tool shell and curl PIDs,47287 and47288, after verifying their identities. Pi PID42044, generated source, server, and harness were left intact. No solution hint or source edit was supplied. The event was recorded before signalling in results/dnd-rest-benchmark/operator-events.jsonl.

This is an operator intervention, not an ordinary benchmark retry or proof of a model limitation. The continuation is retained in its existing run and explicitly flagged in the dashboard. Do not call it an entirely unattended trial or conceal the intervention in analysis. The existing automatic per-agent deadline was disabled; no global deadline or retry-budget change was made.
