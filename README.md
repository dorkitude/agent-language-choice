# Agent Language Choice

Research project started 2026-07-08.

## Overview

Testing code-generation capability of LLM coding agents across programming
languages (Go, Rust, TypeScript, Python, Java, Ruby, PHP), using OSS models via
Fireworks, Claude models via `claude -p`, and OpenAI models via Codex CLI.
Goal: explain performance differences via language *design dimensions*
(compilation/verification signal, ecosystem churn, stdlib coverage,
verbosity, explicitness, idiom uniformity), controlling for training-corpus
prevalence.

The current primary empirical contrast is Go/Rust-style explicit,
compiler-backed, locally inspectable code versus Ruby/Rails-style convention,
dynamic dispatch, and framework-mediated semantics. TypeScript remains a
secondary contrast for ecosystem churn and dependency-surface effects.

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

The full 5-model by 15-target D&D REST lifecycle matrix is summarized in
[`docs/findings/002-full-lifecycle-matrix.md`](docs/findings/002-full-lifecycle-matrix.md).

A self-contained HTML findings report can be generated from embedded JSON with:

```sh
experiments/dnd-rest-benchmark/dashboard/build-self-contained-report.sh
```

The generated files are
[`results/dnd-rest-benchmark/findings-data.json`](results/dnd-rest-benchmark/findings-data.json)
and
[`results/dnd-rest-benchmark/dnd-rest-findings.html`](results/dnd-rest-benchmark/dnd-rest-findings.html).

## Research Log

- 2026-07-12: Reframed the primary contrast around Go/Rust explicit,
  compiler-backed targets versus Ruby/Rails convention-heavy targets.
- 2026-07-12: Added `rust-stdlib` as an append-only 15th target with Rust
  1.97.0 and stdlib-only HTTP/JSON constraints.
- 2026-07-12: Ran `rust-stdlib` across `opus`, `sonnet`, `gpt-5.5`,
  `kimi-k2p7-code`, and `glm-5p2`. Rust passed for Opus and GPT in 11 shots,
  failed for Sonnet at `phb-rules`, and failed for Kimi and GLM at
  `combat-state`.
- 2026-07-12: Exported the updated dashboard JSON, regenerated findings, and
  added a Tokyo Night self-contained HTML report builder for gist publishing.

## Folders

- `experiments/` — experiment designs and code
- `results/` — experiment outputs
- `records/` — correspondence, submissions, and other records
- `docs/` — indexed roadmap, prompt, and findings notes

## License

MIT. See [`LICENSE`](LICENSE).
