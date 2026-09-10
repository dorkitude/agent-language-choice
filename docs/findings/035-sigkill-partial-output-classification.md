# SIGKILL with partial output

Source decision: finish the full five-model, 17-target, 100-stage matrix and standalone dashboard; track work in https://github.com/dorkitude/agent-language-choice/issues/6.

The classifier treated SIGKILL as infrastructure only when both logs were empty. Interrupted CLI processes with startup or partial output therefore consumed model failure budgets. Non-timeout SIGKILL now follows SIGTERM as `agent_killed`, preserving the existing timeout precedence. Eight harness tests pass, including partial-output SIGKILL and timeout cases.

Reindexed the stopped duplicate runs under exclusive cell locks, verifying raw JSON hashes remained unchanged:

- `20260910T071700Z_codex_gpt-5.6-terra_ruby-rails`: status fail, 13 infrastructure shots, needs retry True.
- `20260910T085201Z_codex_gpt-5.6-terra_php-stdlib`: status blocked, 13 infrastructure shots, needs retry True.
- `20260910T103710Z_codex_gpt-5.6-terra_python-flask`: status blocked, 10 infrastructure shots, needs retry True.

Rails can retain a top-level failure label because its last process returned zero, but corrected infrastructure shots make its exhausted budget retryable. These runs remain unresolved. The already-running batch has the old classifier loaded; the fix applies to fresh processes and reconciliation. No generated implementation was edited.

## Additional stopped duplicates, September 10

Reconciliation after 12:03 UTC acquired each cell lock and preserved the raw JSON byte hashes. All three remain retryable; no new deterministic model failure is established.

| Run | Completed stages | Corrected status | Infrastructure shots | Raw JSON SHA-256 |
| --- | ---: | --- | ---: | --- |
| `20260910T105939Z_codex_gpt-5.6-terra_python-stdlib` | 17 | fail, retryable | 7 | `cdc5abaf6d83e03bbe7050ceb6b88dd899b7a46781c20ddec99ad524124b1cdc` |
| `20260910T110116Z_codex_gpt-5.6-terra_java-stdlib` | 24 | blocked | 12 | `907b3b24e78c5536b1b6c4a536b04ed352c216f52160977e8fe911771c6af071` |
| `20260910T114107Z_codex_gpt-5.6-terra_ruby-sinatra` | 9 | blocked | 9 | `40e8187eedd80714607a487ab4c808100d1e6d4c67ee0fb047860f784cada7b2` |

The original completed GPT runs remain intact. Duplicate reconciliation and remaining model runs are still required before final reporting. Local receipt: `results/dnd-rest-benchmark/.cache/resume-20260909/duplicate-gpt-reclassification-1205.json`.
