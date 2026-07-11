# D&D REST Lifecycle Roadmap

This folder is the filename-indexed roadmap for the D&D REST benchmark. Each
stage is a backlog item applied to the same codebase by a fresh agent. The
evaluator suite for each stage is cumulative, so passing a later stage requires
preserving every earlier behavior.

## Lifecycle Model

1. A creative agent builds stage 1 from starter files.
2. If a stage fails, a fresh bug-fix agent receives deterministic evaluator
   failures and gets another shot.
3. If a stage passes, a fresh maintenance agent inherits the codebase and adds
   the next stage.
4. Every creative, maintenance, or bug-fix invocation counts as one shot.

## Stage Index

| File | Stage | Status | Evaluator suite |
| --- | --- | --- | --- |
| [001-core.md](001-core.md) | Core D&D engine API | Completed in full lifecycle matrix | `core` |
| [002-characters.md](002-characters.md) | Character rules | Completed in full lifecycle matrix | `characters` |
| [003-combat-state.md](003-combat-state.md) | Stateful combat sessions | Completed in full lifecycle matrix | `combat-state` |
| [004-auth-users.md](004-auth-users.md) | Username/password auth | Completed in full lifecycle matrix | `auth-users` |
| [005-sqlite-storage.md](005-sqlite-storage.md) | SQLite persistence | Completed in full lifecycle matrix | `sqlite-storage` |
| [006-compendium.md](006-compendium.md) | Monster/item compendium | Completed in full lifecycle matrix | `compendium` |
| [007-campaign-state.md](007-campaign-state.md) | Campaign state APIs | Completed in full lifecycle matrix | `campaign-state` |
| [008-phb-rules.md](008-phb-rules.md) | Selected PHB rules | Completed in full lifecycle matrix | `phb-rules` |
| [009-dm-tools.md](009-dm-tools.md) | DM-facing helpers | Completed in full lifecycle matrix | `dm-tools` |
| [010-prompt-template.md](010-prompt-template.md) | Agent prompt contract | Active | n/a |

## Harness Hooks

- Stage ordering lives in
  [`experiments/dnd-rest-benchmark/rest_harness.py`](../../experiments/dnd-rest-benchmark/rest_harness.py).
- Challenge contracts live in
  [`experiments/dnd-rest-benchmark/challenges/`](../../experiments/dnd-rest-benchmark/challenges/).
- Cumulative evaluator suites live in
  [`experiments/dnd-rest-benchmark/evaluator/internal/eval/suite.go`](../../experiments/dnd-rest-benchmark/evaluator/internal/eval/suite.go).

Run the planned matrix without invoking agents:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py lifecycle-plan --max-fix-shots 1
```
