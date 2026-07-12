# D&D REST Benchmark

REST API benchmark suite for the agent language-choice study.

This suite is designed to stress language/framework properties while keeping
evaluation language-agnostic: the evaluator only talks HTTP.

The initial framing used Go versus TypeScript as the headline contrast. The
first full lifecycle matrix showed that TypeScript, especially Vite, was not
the strongest weak case. The current primary contrast is explicit,
compiler-backed, locally inspectable targets such as Go and Rust versus
Ruby/Rails-style convention, dynamic dispatch, and framework-mediated
semantics. TypeScript remains a secondary contrast for ecosystem churn and
dependency-surface effects.

## Implementation Contract

An agent implementation must provide a server process that:

- Listens on `127.0.0.1:${PORT}` using the `PORT` environment variable.
- Speaks HTTP/JSON only.
- Uses no network access at runtime.
- Persists any in-memory state only for the lifetime of the process.
- Returns JSON responses for success cases.
- Returns a non-2xx status for invalid requests.

The benchmark harness should start the server, wait for `GET /health`, and then
run the central evaluator against its base URL.

## Evaluator

The central evaluator is written in Go with Cobra/Viper:

```sh
cd experiments/dnd-rest-benchmark/evaluator
go run . list
go run . run --base-url http://127.0.0.1:8080 --suite core
```

It can also write a JSON report:

```sh
go run . run \
  --base-url http://127.0.0.1:8080 \
  --suite core \
  --json-out report.json
```

Environment variables use the `DNDEVAL_` prefix, for example:

```sh
DNDEVAL_BASE_URL=http://127.0.0.1:9000 go run . run
```

## Core Suite

The first D&D engine suite evaluates:

- Health endpoint
- Dice expression statistics
- Ability-check totals and margins
- Encounter adjusted XP and difficulty classification
- Initiative ordering with deterministic tie-breakers

See [challenges/core.md](challenges/core.md) for the full API contract.

## Lifecycle Mode

The lifecycle harness simulates a long-lived codebase:

1. A creative agent builds the first implementation from starter files.
2. If a stage fails, a fresh bug-fix agent receives the deterministic evaluator
   failure output and gets another shot.
3. If a stage passes, a fresh maintenance agent inherits the same codebase and
   adds the next feature stage.

Each agent invocation counts as one shot. Stage suites are cumulative, so a
maintenance agent must preserve all previous behavior.

Current lifecycle stages:

- `core`: initial D&D REST API creation, evaluated with suite `core`.
- `characters`: adds character-rule endpoints, evaluated with cumulative suite
  `characters`.
- `combat-state`: adds stateful combat sessions, evaluated with cumulative suite
  `combat-state`.
- `auth-users`: adds deterministic username/password registration and login,
  evaluated with cumulative suite `auth-users`.
- `sqlite-storage`: adds SQLite storage health/reset behavior, evaluated with
  cumulative suite `sqlite-storage`.
- `compendium`: adds monster and item compendium APIs, evaluated with
  cumulative suite `compendium`.
- `campaign-state`: adds campaign, character, and event-log APIs, evaluated
  with cumulative suite `campaign-state`.
- `phb-rules`: adds selected PHB-style rules endpoints, evaluated with
  cumulative suite `phb-rules`.
- `dm-tools`: adds DM encounter, loot, and recap helpers, evaluated with
  cumulative suite `dm-tools`.

The indexed roadmap, prompt contract, and stage-by-stage notes are in
[`../../docs/roadmap/`](../../docs/roadmap/). Findings from completed runs are
in [`../../docs/findings/`](../../docs/findings/).

Current target set includes Go, Rust, TypeScript, Python, Java, Ruby, and PHP
variants. Rust is stdlib-only: agents must use `rustc` and `std::net` without
HTTP crates.

Plan a lifecycle run:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py lifecycle-plan \
  --max-fix-shots 1
```

Run the lifecycle matrix:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py run-lifecycle-matrix \
  --continue-on-fail \
  --skip-existing \
  --max-fix-shots 1 \
  --agent-timeout 900 \
  --setup-timeout 900 \
  --server-timeout 60
```

## First Full Matrix

The first full 5 model x 10 language/framework run is summarized in
[`../../results/dnd-rest-benchmark/MATRIX-2026-07-09.md`](../../results/dnd-rest-benchmark/MATRIX-2026-07-09.md).

An extended 5 model x 14 target run, adding Flask, Django, Slim, and Symfony
components, is summarized in
[`../../results/dnd-rest-benchmark/MATRIX-EXTENDED-2026-07-09.md`](../../results/dnd-rest-benchmark/MATRIX-EXTENDED-2026-07-09.md).

Run command:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py run-matrix \
  --continue-on-fail \
  --skip-existing \
  --agent-timeout 900 \
  --setup-timeout 900 \
  --server-timeout 60
```
