# Infrastructure Block Classification

Data sources:

- [`results/dnd-rest-benchmark/experiment-state.sqlite3`](../../results/dnd-rest-benchmark/experiment-state.sqlite3)
- [`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)

Date: 2026-07-12.

## Finding

Several Claude CLI runs previously counted as ordinary benchmark failures were
actually infrastructure-blocked shots. The captured `agent_stdout.txt` for those
shots contains Claude session/quota-limit messages, not generated code.

The harness now classifies these agent exits as `blocked` rather than `fail`
when stdout/stderr indicates quota, session-limit, auth, or rate-limit
conditions.

## Reclassified State

Across all stored D&D REST benchmark artifacts:

| Status | Runs |
| --- | ---: |
| `pass` | 152 |
| `fail` | 36 |
| `blocked` | 27 |

For the 75-cell nine-stage lifecycle matrix:

| Model | Pass | Fail | Blocked |
| --- | ---: | ---: | ---: |
| `claude/opus` | 5 | 0 | 10 |
| `claude/sonnet` | 2 | 2 | 11 |
| `codex/gpt-5.5` | 13 | 2 | 0 |
| `pi/glm-5p2` | 10 | 5 | 0 |
| `pi/kimi-k2p7-code` | 11 | 4 | 0 |

This means the earlier apparent Claude underperformance should not be treated
as a clean model-quality result. Many cells require reruns under confirmed
available Claude quota before inclusion in comparative model analysis.

## Query

Rebuild the SQLite state database and list affected shots:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py sync-state-db
python3 experiments/dnd-rest-benchmark/rest_harness.py list-infra-blocks
```

The SQLite database indexes run metadata, shot status, agent exit class,
deterministic evaluator counts, and artifact file hashes. Large prompt and
response bodies remain in the artifact tree rather than being duplicated into
SQLite.
