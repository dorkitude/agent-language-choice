# Agent Language Choice — Research Design

Started 2026-07-08. Status: **design draft v0.1** (framing + hypotheses; benchmark and
citations not yet finalized).

## Research question

Why do LLM coding agents appear to perform better in some programming languages
(e.g. Go) than others (e.g. Ruby), and which *language design dimensions*
explain the difference?

We do not claim any language is "better." We treat languages as points in a
design space and test whether position along specific design dimensions
predicts agent task success, independent of training-corpus prevalence.

## Design dimensions (independent variables)

Each dimension is stated as a mechanism hypothesis, with a measurable proxy and
candidate literature. **All citations below are candidates from memory and must
be verified before use** (see Open tasks).

### D1. Verification signal quality (compilation)

**Hypothesis:** Ahead-of-time compiled, statically typed languages give the
agent a fast, deterministic, high-precision error oracle. Agentic loops are
iterative repair loops; the quality of the repair signal bounds the loop's
convergence.

- Proxy: static vs dynamic; AOT-compiled vs interpreted; typechecker
  strictness; time-to-first-error.
- Candidate citations: Olausson et al. 2023, "Is Self-Repair a Silver Bullet?";
  Chen et al. 2023, "Teaching Large Language Models to Self-Debug"; Gao, Bird
  & Barr, ICSE 2017, "To Type or Not to Type" (TS catches ~15% of JS bugs);
  Hanenberg's static-typing experiments; Ray et al., FSE 2014, "A Large-Scale
  Study of Programming Languages and Code Quality in GitHub" (and its
  replication critique — cite both).

### D2. Ecosystem volatility (library churn)

**Hypothesis:** High API churn makes the model's training data stale relative
to the live ecosystem. The agent emits idioms/APIs that were correct at
training time but no longer resolve — version-mismatch errors, deprecated
APIs, hallucinated packages. Critically, breaking changes that land *after a
model's training cutoff* are invisible to the model by construction; the more
volatile the ecosystem, the larger the gap between the model's knowledge and
the environment it must operate in (the TS/npm ecosystem routinely ships such
breaking changes; Go's compatibility promise makes them rare).

- Proxy: dependency-network evolution stats per ecosystem (release cadence,
  breaking-change frequency, median package age at use); deps required per
  solved benchmark task.
- Candidate citations: Decan, Mens & Grosjean, EMSE 2019 (dependency network
  evolution across npm/PyPI/RubyGems/etc.); Kula et al. on outdated
  dependencies; Abdalkareem et al. on trivial npm packages; recent
  hallucinated-package ("slopsquatting") security reports.

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
- Candidate citations: Hindle et al., ICSE 2012, "On the Naturalness of
  Software"; follow-on naturalness literature.

### D5. Explicitness / referential locality

**Hypothesis:** In explicit languages, the meaning of a code region is
determinable from local context, and crucially, *from the import chain*: what
a name refers to is traceable through explicit imports. Implicit constructs
break this: monkey-patching and global-namespace pollution (Ruby core
extensions à la ActiveSupport), convention-over-configuration frameworks
(Rails autoloading — constants resolve with no visible require/import),
decorators/metaclasses, implicit conversions, DI magic, TS structural-typing
edge cases. These require whole-program (or whole-framework) inference the
agent may not perform within its context window. Ruby is the sharpest case:
convention-based dispatch plus namespace pollution means the semantics of a
file are not self-evident from its imports.

- Proxy: qualitative rubric initially (language feature checklist: dynamic
  dispatch surprises, metaprogramming prevalence, implicit conversions);
  possibly "how far away can code change the meaning of this line" as a
  static measure.
- Candidate citations: Pike 2012, "Go at Google: Language Design in the
  Service of Software Engineering" (explicit design rationale — citable as
  design intent, not as evidence of effect).

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

Python/TS/JS dominate public code corpora. MultiPL-E (Cassano et al. 2023) and
MBXP (Athiwaratkun et al. 2023) show LLM performance correlates with language
resource level. Corpus prevalence predicts TS ≥ Go — so if Go wins anyway, the
design-dimension story *strengthens*. Include corpus prevalence (e.g. The
Stack / GitHub language shares) as a covariate in all analyses.

## Languages under test

Go, TypeScript, Python, Java, Ruby, PHP. Candidates to add: Rust (compiled +
strict but low-uniformity/steep semantics — separates D1 from D6), C#.

Preliminary placement (to be replaced with cited/measured values — this table
is our hypothesis, not a result):

| Dimension | Go | TypeScript | Python | Java | Ruby | PHP |
|---|---|---|---|---|---|---|
| D1 compile/type signal | high | mid-high (tsc, but `any`/config-dependent) | low (opt. hints) | high | low | low-mid |
| D2 ecosystem stability | high | low (npm churn) | mid | high | mid | mid |
| D3 stdlib coverage | high | low (Node stdlib thin) | high | high | mid | mid-high |
| D4 verbosity/redundancy | high | mid | low | high | low | mid |
| D5 explicitness | high | mid | low (metaclasses etc.) | mid-high | low (monkey-patching) | mid |
| D6 idiom uniformity | high (gofmt) | low | mid (PEP8, but many frameworks) | mid | mid | low |
| C1 corpus prevalence | mid | high | high | high | mid | mid-high |

Each cell needs either a citation or a measurement before the paper.

## Benchmark design

Requirement: task difficulty must be identical across languages, and the eval
must be agentic (edit → build → run → repair), since D1 lives in the loop.

**Chosen direction (draft): spec-conformance tasks with language-agnostic
black-box tests.** N small tasks (CLI tools and HTTP services) defined by a
natural-language spec + a conformance test suite that exercises the artifact
externally (stdin/stdout, HTTP), so the same tests judge every language.
This avoids the MultiPL-E trap of per-language transpiled unit tests, and it
naturally exercises deps/stdlib (D2/D3).

Task categories (draft): text/data munging (stdlib-only solvable), HTTP JSON
API, concurrency (rate limiter, worker pool), third-party-dependency-required
task (deliberately probes D2), refactor/extend-existing-code task (probes D5 —
requires seeding per-language starter repos, held structurally parallel).

REST/API tasks should be a primary stressor for the Go vs TypeScript contrast:
Go's standard library includes production-usable HTTP server and JSON support,
while TypeScript without npm packages must use lower-level Node HTTP APIs,
manual routing/body parsing, and a separate compile/runtime path. To keep this
like-for-like, evaluate REST tasks only through a central black-box HTTP
evaluator.

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

- **OSS models via Fireworks** (e.g. current Qwen-coder / DeepSeek / Llama
  coder variants — pin exact versions at experiment time)
- **Claude models via `claude -p`** (headless Claude Code; pin model IDs)
- **OpenAI models via Codex CLI**

Harness requirements: identical prompt/spec per task across providers; each
run in an isolated workspace (container) with the language toolchain
pre-installed; fixed iteration budget; full transcript + artifact capture;
seeds/configs recorded for reproducibility.

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
- TS is config-dependent (strict mode vs not) — must fix and report tsconfig.

## Open tasks

- [ ] Verify every candidate citation above (deep-research pass); replace
      from-memory attributions with confirmed refs
- [ ] Score the language × dimension matrix with citations/measurements
- [ ] Finalize task list (target: 20–30 tasks × 6 languages)
- [x] Build initial harness (Fireworks/Pi + `claude -p` + Codex CLI runners)
- [x] Build first central REST evaluator (Go/Cobra/Viper) for D&D engine API
      challenges
- [ ] Pilot: greenfield + debugging tasks × all six languages × selected
      models (started with `kv_patch` × Go/TS × GLM/Kimi on 2026-07-08;
      `ledger_debug` now seeds equivalent buggy repos for all languages)
- [ ] Pick target venue (IES again? ICSE/FSE/ASE? NeurIPS D&B track?)
