# Agent Language Choice

Independent research project investigating the effect of language & framework choice on
agentic code generation.  Studying the effects of these specific design dimensions:

- compilation/verification signal
- ecosystem churn
- stdlib coverage
- verbosity
- explicitness
- idiom uniformity



## Overview

Testing code-generation capability of LLM coding agents across multiple
language/framework targets, using OSS models via Pi (GPUs hosted on Fireworks), Claude models via
`claude -p`, and OpenAI models via Codex CLI.
Goal: explain performance differences via language *design dimensions*
(compilation/verification signal, ecosystem churn, stdlib coverage,
verbosity, explicitness, idiom uniformity), controlling for training-corpus
prevalence.

The current benchmark is empirical: each model/target cell is driven through a
cumulative feature roadmap, with pass/fail stage, total shots, and deterministic
evaluator output recorded as data. The goal is to measure which design
dimensions predict agent success as a codebase grows, not to preselect a winner.

See [`RESEARCH-DESIGN.md`](RESEARCH-DESIGN.md) for hypotheses, the
language × dimension matrix, benchmark design, and open tasks.

The first runnable benchmark harness is in
[`experiments/codegen-benchmark/`](experiments/codegen-benchmark/). Initial
pilot results are in
[`results/codegen-benchmark/PILOT-2026-07-08.md`](results/codegen-benchmark/PILOT-2026-07-08.md).

The first REST/API benchmark suite is in
[`experiments/dnd-rest-benchmark/`](experiments/dnd-rest-benchmark/). It uses a
central Go evaluator for D&D engine API challenges.

The staged D&D lifecycle roadmap, prompt contract, and future backlog are in
[`docs/roadmap/`](docs/roadmap/). Results and early interpretation are in
[`docs/findings/`](docs/findings/).

The completed 5-model by 15-target D&D REST lifecycle matrix is summarized in
[`docs/findings/002-full-lifecycle-matrix.md`](docs/findings/002-full-lifecycle-matrix.md).
That completed matrix used nine cumulative stages.

The default D&D REST roadmap now has 16 total stages: one initial creative
build plus 15 fresh maintenance inheritances. The final suite,
`analytics-reporting`, contains 58 cumulative deterministic HTTP checks.

A self-contained HTML findings report can be generated from embedded JSON with:

```sh
experiments/dnd-rest-benchmark/dashboard/build-self-contained-report.sh
```

The generated files are
[`results/dnd-rest-benchmark/findings-data.json`](results/dnd-rest-benchmark/findings-data.json)
and
[`results/dnd-rest-benchmark/dnd-rest-findings.html`](results/dnd-rest-benchmark/dnd-rest-findings.html).

The queryable experiment-state database is
[`results/dnd-rest-benchmark/experiment-state.sqlite3`](results/dnd-rest-benchmark/experiment-state.sqlite3).
Rebuild it from JSON artifacts and list infrastructure-blocked shots with:

```sh
python3 experiments/dnd-rest-benchmark/rest_harness.py sync-state-db
python3 experiments/dnd-rest-benchmark/rest_harness.py list-infra-blocks
```

Published preview:
<https://htmlpreview.github.io/?https://gist.githubusercontent.com/dorkitude/a842e88a90e822e4ca0f8f98da7d04e1/raw/c083ee9fa0ad55fe3dc9a54746695a63f046eaac/dnd-rest-findings.html>

## Research Log

- 2026-07-12: Added infrastructure-block classification for agent exits caused
  by CLI quota/session/auth/rate-limit conditions. Rebuilt the D&D REST
  dashboard and SQLite experiment-state DB; 27 stored runs are now marked
  `blocked` instead of ordinary failures.
- 2026-07-12: Added `rust-stdlib` as an append-only target with Rust
  1.97.0 and stdlib-only HTTP/JSON constraints.
- 2026-07-12: Ran `rust-stdlib` across `opus`, `sonnet`, `gpt-5.5`,
  `kimi-k2p7-code`, and `glm-5p2`. Rust passed for Opus and GPT in 11 shots,
  failed for Sonnet at `phb-rules`, and failed for Kimi and GLM at
  `combat-state`.
- 2026-07-12: Exported the updated dashboard JSON, regenerated findings, and
  added a Tokyo Night self-contained HTML report builder for gist publishing.
- 2026-07-12: Extended the default lifecycle roadmap to 16 stages, giving each
  cell 15 fresh maintenance inheritances after the initial build. Added
  deterministic evaluator suites through `analytics-reporting`.
- 2026-07-11: Added the full nine-stage D&D lifecycle matrix: 75 cells across
  five models and 15 targets, 41 full lifecycle passes, 34 failed cells, and
  635 total shots. `gpt-5.5` led at 13/15 completed cells.
- 2026-07-11: Promoted shot burden, failed stage, and bug-fix recovery from
  bookkeeping into first-class outcomes after many successful cells required
  11-15 shots rather than the clean nine-shot minimum.
- 2026-07-11: Added the MIT license, removed private credential fallback
  references, and tightened the research design notes for public release.
- 2026-07-10: Expanded the D&D REST benchmark roadmap and early lifecycle
  results. The stored 70-cell run set covered `core`, `characters`, and
  `combat-state`, with 54 passing cells, 16 failing cells, and 281 total shots.
- 2026-07-10: Aligned challenge specs and evaluator behavior for later roadmap
  stages, including auth, campaign state, PHB rules, DM tools, and compendium
  scoring details.
- 2026-07-09: Ran the initial D&D REST matrix: 5 models by 10
  language/framework targets, 39/50 passing. Opus went 10/10, Sonnet and GLM
  went 9/10, and TypeScript/Next.js failures were mostly startup/health
  failures.
- 2026-07-09: Extended the matrix to 14 targets by adding Flask, Django, Slim,
  and Symfony. The extended matrix reached 57/70 passing; Flask and Django both
  went 5/5, while Kimi showed a recurring negative dice modifier failure mode.
- 2026-07-08: Started the agent language choice project and wrote the initial
  benchmark design around language design dimensions, ecosystem/tooling
  controls, and cumulative codebase-growth pressure.
- 2026-07-08: Built the first codegen benchmark harness and smoke pilot. All
  eight pilot runs passed across `kv_patch` and `ledger_debug`; TypeScript took
  materially longer than Go on the shared `kv_patch` task.

## Folders

- `experiments/` — experiment designs and code
- `results/` — experiment outputs
- `records/` — correspondence, submissions, and other records
- `docs/` — indexed roadmap, prompt, and findings notes

## License

MIT. See [`LICENSE`](LICENSE).
