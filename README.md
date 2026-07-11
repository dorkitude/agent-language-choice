# Agent Language Choice

Research project started 2026-07-08.

## Overview

Testing code-generation capability of LLM coding agents across programming
languages (Go, TypeScript, Python, Java, Ruby, PHP), using OSS models via
Fireworks, Claude models via `claude -p`, and OpenAI models via Codex CLI.
Goal: explain performance differences via language *design dimensions*
(compilation/verification signal, ecosystem churn, stdlib coverage,
verbosity, explicitness, idiom uniformity), controlling for training-corpus
prevalence.

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

The full 5-model by 14-target D&D REST lifecycle matrix is summarized in
[`docs/findings/002-full-lifecycle-matrix.md`](docs/findings/002-full-lifecycle-matrix.md).

## Folders

- `experiments/` — experiment designs and code
- `results/` — experiment outputs
- `records/` — correspondence, submissions, and other records
- `docs/` — indexed roadmap, prompt, and findings notes

## License

MIT. See [`LICENSE`](LICENSE).
