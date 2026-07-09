# Codegen Benchmark Harness

Pilot harness for comparing coding agents across programming languages.

The benchmark uses language-agnostic black-box CLI tasks. For each run, the
agent receives a task spec and a target language, then must create a local
`run.sh`. The harness tests `./run.sh` through stdin/stdout only.

## Current scope

- Providers:
  - `pi` for open-weight Fireworks models such as `kimi-k2p7-code` and `glm-5p2`
  - `claude` via `claude -p`
  - `codex` via `codex exec`
- Languages:
  - Go, TypeScript, Python, Java, Ruby, PHP
- Pilot tasks:
  - `kv_patch`: stateful patch application from JSON lines
  - `window_counts`: sliding-window event aggregation
  - `route_params`: route-template matching
  - `ledger_debug`: seeded pre-existing repo debugging task

## Chosen model matrix

| Label | Provider | CLI model argument | Notes |
|---|---|---|---|
| `claude-opus-latest` | `claude` | `opus` | Claude CLI alias for newest Opus |
| `claude-sonnet-latest` | `claude` | `sonnet` | Claude CLI alias for newest Sonnet |
| `gpt-5.5-medium` | `codex` | `gpt-5.5` | Codex model with `model_reasoning_effort="medium"` |
| `kimi-k2p7-code` | `pi`/Fireworks | `kimi-k2p7-code` | Mapped to `accounts/fireworks/models/kimi-k2p7-code` |
| `glm-5p2` | `pi`/Fireworks | `glm-5p2` | Mapped to `accounts/fireworks/models/glm-5p2` |

`gpt-5.5-medium` is a benchmark label, not a Codex model ID. The current
Codex manual names `gpt-5.5` as the recommended model; "medium" is represented
as Codex reasoning effort.

## Local toolchain status on 2026-07-08

Available here: Go, Node/TypeScript (`node`, `tsc`), Python 3, Ruby, PHP
8.5.8, and OpenJDK/Javac 26.0.1.

OpenJDK is installed through Homebrew and is keg-only, so the harness prepends
`/opt/homebrew/opt/openjdk/bin` to `PATH` for agent and test subprocesses.

## Examples

List tasks:

```sh
python3 experiments/codegen-benchmark/harness.py list-tasks
```

Run GLM 5.2 through Fireworks/Pi on Go:

```sh
python3 experiments/codegen-benchmark/harness.py run \
  --provider pi \
  --model glm-5p2 \
  --language go \
  --task kv_patch
```

Run Kimi 2.7 Code through Fireworks/Pi on TypeScript:

```sh
python3 experiments/codegen-benchmark/harness.py run \
  --provider pi \
  --model kimi-k2p7-code \
  --language typescript \
  --task kv_patch
```

Run Claude:

```sh
python3 experiments/codegen-benchmark/harness.py run \
  --provider claude \
  --model opus \
  --language go \
  --task kv_patch
```

Run Codex:

```sh
python3 experiments/codegen-benchmark/harness.py run \
  --provider codex \
  --model gpt-5-codex \
  --language go \
  --task kv_patch
```

Plan the full matrix for all selected models, languages, and tasks:

```sh
python3 experiments/codegen-benchmark/harness.py matrix-plan
```

Run the full matrix, resuming around completed successful runs:

```sh
python3 experiments/codegen-benchmark/harness.py run-matrix \
  --skip-existing \
  --continue-on-fail
```

Run only the open-weight models across all languages for the current pilot
tasks:

```sh
python3 experiments/codegen-benchmark/harness.py run-matrix \
  --models kimi-k2p7-code,glm-5p2 \
  --tasks kv_patch,window_counts,route_params,ledger_debug \
  --skip-existing \
  --continue-on-fail
```

## Pre-existing repo debugging

`ledger_debug` is intentionally a separate task category. Each language gets a
structurally parallel starter repo with the same logical bug, and the same
black-box tests score all languages. In analysis, treat task category
(`greenfield` vs `preexisting-repo-debugging`) as a covariate or random effect
instead of mixing the two as identical task types.

## Fireworks auth

The harness follows the ISC experiment's credential order:

1. `FIREWORKS_API_KEY`
2. `LLM_GATEWAY_DEFAULT_FIREWORKS_API_KEY`
3. `--op-ref` with `op read`

The key is passed to `pi` through the child-process environment, not as a
command-line argument.

## Outputs

Runs are written under `results/codegen-benchmark/runs/`:

- `metadata.json`: provider/model/language/task/timestamps
- `TASK.md`: exact prompt task contract
- `agent_stdout.txt` and `agent_stderr.txt`
- `result.json`: test results and aggregate pass/fail
- generated source artifacts
