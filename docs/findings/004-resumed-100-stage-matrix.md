# 100-stage lifecycle experiment resumed

Date: 2026-09-09. Operational tracker: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

## Decision context

Kyle: “unpause it and then resume work on it.” Follow-up: “no i want them recorded in the same place.” Final instruction: “do it.”

Continuations append to the existing lifecycle directories, experiment-state.sqlite3, and dashboard. Existing shots remain intact. No new September experiment is created. Old submission deadlines are not renewed.

## State before resuming

Latest attempt per provider/model/target in the local SQLite database:

| Model | Cells represented | Pass | Fail | Blocked | Partial | Timeout |
|---|---:|---:|---:|---:|---:|---:|
| Claude Opus 5 | 17 | 0 | 0 | 17 | 0 | 0 |
| Claude Sonnet 5 | 17 | 9 | 1 | 0 | 0 | 7 |
| GPT-5.6 Terra | 16 | 4 | 2 | 0 | 5 | 5 |
| GLM 5.2 | 8 | 0 | 0 | 4 | 4 | 0 |
| Kimi K2.7 Code | 17 | 4 | 0 | 3 | 5 | 5 |

These are operational statuses, not model rankings. Ten of the 85 planned cells have no latest-attempt row. The database contains 118 historical run rows, including 18 passes; deduplicating to latest attempts yields 17 passes.

## Restart receipt

- No existing rest_harness.py process was running.
- Local SQLite backup: results/dnd-rest-benchmark/.cache/resume-20260909/before-resume.sqlite3.
- Validation: go test ./... in experiments/dnd-rest-benchmark/evaluator passed.
- Resumed directory: results/dnd-rest-benchmark/lifecycle-runs/20260805T232657Z_codex_gpt-5.6-terra_rust-stdlib.
- Started 2026-09-09T07:52:22Z, PID 48204, continuing at stage 095-fixture-seeding after 94 passes.
- Existing budget retained: five bug-fix retries, medium reasoning, original model identifier.
- Detached run log and launch receipt: results/dnd-rest-benchmark/.cache/resume-20260909/. caffeinate follows the harness PID.

The working tree includes earlier uncommitted harness fixes and run artifacts. This restart preserves those files; it does not claim they have all been audited or published. New runs must continue to exclude evaluator deadlines and infrastructure blocks from capability comparisons. The elapsed time between August and September and any observable tool/model-version changes must remain visible when analyzing the combined records.
