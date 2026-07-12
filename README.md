# Agent Language Choice

Research project started 2026-07-08.

## Overview

Testing code-generation capability of LLM coding agents across multiple
language/framework targets, using OSS models via Fireworks, Claude models via
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

Published preview:
<https://htmlpreview.github.io/?https://gist.githubusercontent.com/dorkitude/a842e88a90e822e4ca0f8f98da7d04e1/raw/dnd-rest-findings.html>

## Research Log

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

## Folders

- `experiments/` — experiment designs and code
- `results/` — experiment outputs
- `records/` — correspondence, submissions, and other records
- `docs/` — indexed roadmap, prompt, and findings notes

## License

MIT. See [`LICENSE`](LICENSE).
