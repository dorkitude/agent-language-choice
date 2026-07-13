# Infrastructure Block Classification

Data sources:

- [`results/dnd-rest-benchmark/experiment-state.sqlite3`](../../results/dnd-rest-benchmark/experiment-state.sqlite3)
- [`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)

Date: 2026-07-12. Updated after Claude reruns on 2026-07-13.

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
| `pass` | 170 |
| `fail` | 39 |
| `blocked` | 27 |

Shot-level agent exit classes:

| Agent exit class | Shots |
| --- | ---: |
| `ok` | 1146 |
| `quota_limit` | 53 |
| `timeout` | 13 |

The latest 75-cell nine-stage lifecycle matrix now uses rerun Claude cells
where quota and model selection were confirmed. That current comparative result
is summarized in
[`002-full-lifecycle-matrix.md`](002-full-lifecycle-matrix.md): Opus is 15/15
and Sonnet is 10/15. The older blocked Claude artifacts remain in the state DB
for auditability, but they are no longer interpreted as model-quality failures.

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
