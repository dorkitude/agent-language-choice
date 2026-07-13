# Agent Language Choice — Research Design

Started 2026-07-08. Status: **design draft v0.3** (framing, benchmark,
initial citation verification, target scoring, and venue plan completed).

## Research question

Which language, framework, and ecosystem design dimensions predict LLM coding
agent success as a codebase grows through repeated maintenance tasks?

We do not claim any language is "better." We treat languages as points in a
design space and test whether position along specific design dimensions
predicts agent task success, independent of training-corpus prevalence.

## Design dimensions (independent variables)

Each dimension is stated as a mechanism hypothesis, with a measurable proxy and
verified anchor literature. These references are not yet a complete related-work
section, but they are confirmed enough to support the current design draft.

### D1. Verification signal quality (compilation)

**Hypothesis:** Ahead-of-time compiled, statically typed languages give the
agent a fast, deterministic, high-precision error oracle. Agentic loops are
iterative repair loops; the quality of the repair signal bounds the loop's
convergence.

- Proxy: static vs dynamic; AOT-compiled vs interpreted; typechecker
  strictness; time-to-first-error.
- Anchor citations: Olausson et al. 2024,
  ["Is Self-Repair a Silver Bullet for Code Generation?"](https://arxiv.org/abs/2306.09896);
  Gao, Bird & Barr 2017,
  ["To Type or Not to Type: Quantifying Detectable Bugs in JavaScript"](https://dl.acm.org/doi/10.1109/ICSE.2017.75).
  Use Hanenberg-style static-typing experiments and the Ray et al. language
  quality debate as related work, but do not rely on them as direct causal
  evidence for agent performance.

### D2. Ecosystem volatility (library churn)

**Hypothesis:** High API churn makes the model's training data stale relative
to the live ecosystem. The agent emits idioms/APIs that were correct at
training time but no longer resolve: version-mismatch errors, deprecated APIs,
or hallucinated packages. Critically, breaking changes that land *after a
model's training cutoff* are invisible to the model by construction; the more
volatile the ecosystem, the larger the gap between the model's knowledge and
the environment it must operate in.

- Proxy: dependency-network evolution stats per ecosystem (release cadence,
  breaking-change frequency, median package age at use); deps required per
  solved benchmark task.
- Anchor citations: Decan, Mens & Grosjean 2019,
  ["An Empirical Comparison of Dependency Network Evolution in Seven Software
  Packaging Ecosystems"](https://link.springer.com/article/10.1007/s10664-017-9589-y)
  / [arXiv preprint](https://arxiv.org/abs/1710.04936). Use Kula et al. on
  outdated dependencies and package-hallucination/slopsquatting reports as
  supporting operational risk literature.

### D3. Standard library coverage

**Hypothesis:** A robust stdlib means more of any given task is solvable with
APIs that are stable, heavily represented in training data, and guaranteed
present in the execution environment.

- Proxy: fraction of benchmark tasks solvable with zero third-party deps;
  number of deps agents actually pull in per task.
- Related to D2 but separable: a language can have a strong stdlib *and* a
  churning ecosystem (arguably Python).

### D4. Verbosity / redundancy

**Hypothesis:** Verbose code spreads each semantic decision across more, more
predictable tokens. Redundancy acts as an error-correcting channel for a
probabilistic generator; expressiveness (semantic density per token) makes
each token a higher-stakes decision. Token-efficiency arguments for concise
languages assume a human reader, not a stochastic writer.

- Proxy: tokens per solved task (corpus-level and in our results); language
  entropy per Hindle et al.'s naturalness framing.
- Anchor citation: Hindle et al. 2012,
  ["On the Naturalness of Software"](https://softwareprocess.es/homepage/papers/2012-hindle12012icse/).
  The direct claim from that work is predictability/repetition in human-written
  software; the redundancy-as-error-correction mechanism remains this study's
  hypothesis.

### D5. Explicitness / referential locality

**Hypothesis:** In explicit languages, the meaning of a code region is
determinable from local context, and crucially, *from the import chain*: what
a name refers to is traceable through explicit imports. Implicit constructs
break this: monkey-patching, global-namespace pollution,
convention-over-configuration frameworks, autoloading, decorators/metaclasses,
implicit conversions, dependency-injection magic, and structural-typing edge
cases. These require whole-program or whole-framework inference the agent may
not perform within its context window.

- Proxy: qualitative rubric initially (language feature checklist: dynamic
  dispatch surprises, metaprogramming prevalence, implicit conversions);
  possibly "how far away can code change the meaning of this line" as a
  static measure.
- Anchor citation: Pike 2012,
  ["Go at Google: Language Design in the Service of Software Engineering"](https://go.dev/talks/2012/splash.article)
  as design intent, not direct evidence of agent effect.

### D6. Idiom uniformity

**Hypothesis:** Languages with one canonical style (gofmt, "one obvious way")
concentrate the training distribution: the training corpus is more
*repetitive*, so each idiom is seen more often and learned more reliably —
the same amount of training data yields more signal per pattern. Fewer
competing idioms for the same intent means lower variance in generation and
fewer half-remembered hybrid styles. This interacts with C1: raw corpus size
overstates the useful signal in low-uniformity ecosystems, where the corpus
is spread across many competing framework idioms (and across incompatible
versions of the same framework — see D2).

- Proxy: presence of enforced canonical formatter/style; number of mainstream
  competing frameworks per task category (e.g. HTTP server: Go stdlib vs
  TS's express/fastify/koa/hono/nest...).

### Confound C1. Training-corpus prevalence (must control)

Public code corpora are not evenly distributed across languages and frameworks.
MultiPL-E (Cassano et al. 2023) and MBXP/HumanEval-X (Athiwaratkun et al.
2022/2023) show that multilingual code generation performance varies by
language and benchmark construction. Include corpus prevalence (e.g. The Stack
/ GitHub language shares) as a covariate in all analyses.

- Anchor citations: Cassano et al.,
  ["MultiPL-E: A Scalable and Extensible Approach to Benchmarking Neural Code
  Generation"](https://arxiv.org/abs/2208.08227); Athiwaratkun et al.,
  ["Multi-lingual Evaluation of Code Generation Models"](https://arxiv.org/abs/2210.14868).

## Targets under test

The harness defines multiple language/framework targets. Treat each target as
a point in a measured design space rather than as a pre-labeled good or bad
case.

Initial qualitative scoring for the current benchmark targets:

| Target | Verification signal | Ecosystem volatility | Stdlib/dependency surface | Explicitness/locality | Idiom uniformity | Corpus prevalence |
| --- | --- | --- | --- | --- | --- | --- |
| `go-stdlib` | high | low | high stdlib / zero deps | high | high | medium |
| `rust-stdlib` | high | medium | high stdlib / zero deps in benchmark | high | medium-high | medium-low |
| `java-stdlib` | high | low-medium | high stdlib / zero deps | high | medium | high |
| `typescript-node` | medium-high | high | medium stdlib / npm-adjacent | medium | low-medium | high |
| `typescript-vite` | medium-high | high | framework/toolchain heavy | medium | low-medium | high |
| `typescript-nextjs` | medium-high | high | framework-heavy | medium-low | medium | high |
| `python-stdlib` | low-medium | medium | high stdlib / zero deps | medium | medium | high |
| `python-flask` | low-medium | medium | light framework | medium | medium | high |
| `python-django` | low-medium | medium | framework-heavy, batteries included | medium-low | medium-high | high |
| `ruby-stdlib` | low | medium | medium stdlib / zero deps | low-medium | medium | medium |
| `ruby-sinatra` | low | medium | light framework | low-medium | medium | medium |
| `ruby-rails` | low | medium | framework-heavy, convention-driven | low | medium-high | medium |
| `php-stdlib` | low-medium | medium | medium stdlib / zero deps | medium | medium | medium |
| `php-slim` | low-medium | medium | light framework | medium | medium | medium |
| `php-symfony` | low-medium | medium | framework-components | medium | medium-high | medium |

These are analysis covariates, not conclusions. Paper-ready scoring should
replace qualitative labels with a coded rubric: compile/typecheck feedback,
dependency count, package age/churn, formatter/linter canonicalization,
framework count per task category, and corpus prevalence.

## Benchmark design

Requirement: task difficulty must be identical across languages, and the eval
must be agentic (edit → build → run → repair), since D1 lives in the loop.

**Chosen direction (draft): spec-conformance tasks with language-agnostic
black-box tests.** N small tasks (CLI tools and HTTP services) defined by a
natural-language spec + a conformance test suite that exercises the artifact
externally (stdin/stdout, HTTP), so the same tests judge every language.
This avoids the MultiPL-E trap of per-language transpiled unit tests, and it
naturally exercises deps/stdlib (D2/D3).

Final task strata for the first paper:

1. **Greenfield REST lifecycle:** the D&D engine roadmap below, scored by
   cumulative black-box HTTP suites.
2. **Maintenance inheritance:** every post-`core` D&D stage is implemented by
   a fresh agent inheriting the growing codebase.
3. **Bug-fix recovery:** failed stages receive deterministic evaluator output
   and a fresh bug-fix agent; every attempt counts as a shot.
4. **Seeded debugging:** structurally parallel buggy starter repos for smaller
   CLI/service tasks, scored separately from the greenfield lifecycle.

Finalized first-suite task roadmap:

| # | Task/stage | Stratum | Evaluator |
| ---: | --- | --- | --- |
| 1 | `core` D&D REST API | greenfield | HTTP |
| 2 | `characters` | maintenance | HTTP |
| 3 | `combat-state` | maintenance | HTTP |
| 4 | `auth-users` | maintenance | HTTP |
| 5 | `sqlite-storage` | maintenance | HTTP |
| 6 | `compendium` | maintenance | HTTP |
| 7 | `campaign-state` | maintenance | HTTP |
| 8 | `phb-rules` | maintenance | HTTP |
| 9 | `dm-tools` | maintenance | HTTP |
| 10 | `quest-tracker` | maintenance | HTTP |
| 11 | `npcs-factions` | maintenance | HTTP |
| 12 | `inventory-equipment` | maintenance | HTTP |
| 13 | `downtime-crafting` | maintenance | HTTP |
| 14 | `session-scheduling` | maintenance | HTTP |
| 15 | `audit-export` | maintenance | HTTP |
| 16 | `analytics-reporting` | maintenance | HTTP |
| 17 | `kv_patch` | greenfield CLI/service pilot | CLI/unit |
| 18 | `ledger_debug` | seeded debugging pilot | CLI/unit |
| 19 | rate limiter | concurrency extension | HTTP/CLI |
| 20 | job queue / worker pool | concurrency extension | HTTP/CLI |
| 21 | import/export migration | persistence extension | HTTP |
| 22 | schema migration bugfix | seeded debugging | HTTP/CLI |
| 23 | dependency upgrade repair | ecosystem-volatility probe | framework-native + HTTP |
| 24 | cross-file refactor | referential-locality probe | CLI/unit |

REST/API tasks are evaluated only through a central black-box HTTP evaluator.
This keeps scoring independent of implementation language and lets the same
feature roadmap exercise toolchain feedback, dependency choices, routing,
JSON handling, persistence, and cumulative maintenance behavior.

Pre-existing repo debugging should be treated as a separate benchmark stratum,
not mixed directly with greenfield code generation. It is not necessarily
apples-to-oranges if each language gets a structurally parallel starter repo
with the same logical bug and the same black-box conformance tests. In the
analysis, include task category (greenfield vs debugging/refactor) as a
covariate or random effect.

Existing benchmarks to reuse/compare against (related work, not our
instrument): MultiPL-E, HumanEval-X, MBXP, Aider polyglot leaderboard,
SWE-bench (Python-only — part of the gap we're filling), McEval.

Metrics: pass rate (pass@1 under agentic loop), iterations-to-green, wall
clock, tokens consumed, error-class distribution (compile vs runtime vs
test-fail vs dependency-resolution), third-party deps used.

## Model harness

Three providers, driven uniformly:

- **OSS models via Fireworks/Pi:** `kimi-k2p7-code`, `glm-5p2`
- **Claude models via `claude -p`:** CLI aliases verified on 2026-07-12:
  `opus` resolves to `claude-opus-4-8`, `sonnet` resolves to
  `claude-sonnet-5`, `fable` resolves to `claude-fable-5`
- **OpenAI models via Codex CLI:** `gpt-5.5` with medium reasoning effort

Harness requirements: identical prompt/spec per task across providers; each
run in an isolated workspace (container) with the language toolchain
pre-installed; fixed iteration budget; full transcript + artifact capture;
seeds/configs recorded for reproducibility.

Infrastructure accounting requirement: agent CLI quota/session/auth/rate-limit
exits are classified as `blocked`, not as model failures. See
[`docs/findings/003-infra-block-classification.md`](docs/findings/003-infra-block-classification.md)
and the queryable state DB at
[`results/dnd-rest-benchmark/experiment-state.sqlite3`](results/dnd-rest-benchmark/experiment-state.sqlite3).

Analysis: mixed-effects model — task success ~ language design dimensions +
corpus prevalence covariate, random effects for task and model. Interaction
of interest: dimension × model-capability (do weaker models depend *more* on
D1 feedback?).

## Threats to validity (running list)

- Dimension scores are partly subjective → cite or measure every cell; report
  sensitivity analysis.
- Corpus prevalence covariate is coarse (The Stack shares ≠ each vendor's mix).
- Task authorship bias: specs written by Go-sympathetic authors may encode
  Go-shaped tasks. Mitigate: derive task set from a language-neutral source;
  external review.
- Conformance tests at process/HTTP boundary can't judge code quality —
  scope claims to functional success.
- Framework/runtime version recency is a design choice in this study: targets
  intentionally use newest available versions, which increases ecological
  validity for active coding agents but may increase post-training-cutoff
  volatility.

## Venue plan

Primary target: **ASE research track**. The study is an empirical software
engineering paper about agentic code generation under language/framework
design variables, with a new benchmark harness and artifacts. Strong fallback
venues: **ICSE research track**, **FSE research track**, or an empirical
software engineering journal extension if the benchmark/results need more
space than a conference paper permits.

Workshop/early-feedback targets: an AI-for-SE, LLM4Code, or MSR-adjacent
workshop once the Claude reruns and 16-stage matrix are complete.

## Open tasks

- [x] Verify candidate citations above; replace from-memory attributions with
      confirmed anchor refs
- [x] Score the language × dimension matrix with preliminary qualitative
      citations/measurements
- [x] Finalize task list (24 tasks/stages across greenfield, maintenance,
      bug-fix, debugging, concurrency, dependency, and refactor strata)
- [x] Build initial harness (Fireworks/Pi + `claude -p` + Codex CLI runners)
- [x] Build first central REST evaluator (Go/Cobra/Viper) for D&D engine API
      challenges
- [x] Pilot: greenfield + debugging tasks across selected languages/models;
      superseded by the 15-target D&D REST lifecycle matrix and retained
      `kv_patch` / `ledger_debug` strata as smaller pilot/debugging artifacts
- [x] Pick target venue: primary ASE research track; fallback ICSE/FSE or
      journal extension
