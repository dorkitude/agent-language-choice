# SIGKILL with partial output

Source decision: finish the full five-model, 17-target, 100-stage matrix and standalone dashboard; track work in https://github.com/dorkitude/agent-language-choice/issues/6.

The classifier treated SIGKILL as infrastructure only when both logs were empty. Interrupted CLI processes with startup or partial output therefore consumed model failure budgets. Non-timeout SIGKILL now follows SIGTERM as `agent_killed`, preserving the existing timeout precedence. Eight harness tests pass, including partial-output SIGKILL and timeout cases.

Reindexed the stopped duplicate runs under exclusive cell locks, verifying raw JSON hashes remained unchanged:

- `20260910T071700Z_codex_gpt-5.6-terra_ruby-rails`: status fail, 13 infrastructure shots, needs retry True.
- `20260910T085201Z_codex_gpt-5.6-terra_php-stdlib`: status blocked, 13 infrastructure shots, needs retry True.
- `20260910T103710Z_codex_gpt-5.6-terra_python-flask`: status blocked, 10 infrastructure shots, needs retry True.

Rails can retain a top-level failure label because its last process returned zero, but corrected infrastructure shots make its exhausted budget retryable. These runs remain unresolved. The already-running batch has the old classifier loaded; the fix applies to fresh processes and reconciliation. No generated implementation was edited.
