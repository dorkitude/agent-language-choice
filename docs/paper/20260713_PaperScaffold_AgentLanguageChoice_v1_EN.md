# Paper Scaffold: Agent Language Choice

Version: v1. Date: 2026-07-13. Paper-compiler mode: write. Proposal type:
D, empirical study. Skeleton: IMRAD.

## Working Title

Shot Burden, Failure Stage, and Language Choice in Agentic Code Generation

## Seven-Sentence Abstract Draft

LLM coding agents are increasingly used to build and maintain software, but
their performance is usually reported without isolating the effects of
programming-language and framework choice. We study whether language and
ecosystem design dimensions predict agent success as a codebase grows through
repeated maintenance. We build a deterministic D&D REST API benchmark with
black-box HTTP evaluation, five model families, fifteen language/framework
targets, and cumulative lifecycle stages where fresh agents inherit prior
code. In the latest nine-stage baseline, 75 model/target cells produce 59 full
lifecycle passes, 16 deterministic failures, and 784 total shots. The strongest
current model completes all targets, but even successful cells require extra
repair shots beyond the clean nine-shot minimum. Failures cluster around
stateful and exact-contract maintenance stages, especially combat-state
response-shape drift. These results motivate treating shot burden and failure
stage as first-class outcomes, and they provide a benchmark artifact for
testing how language/framework properties affect agentic software maintenance.

## Introduction Slots

Problem: language/framework choice is an uncontrolled variable in many
agentic-code benchmarks and operational coding-agent deployments.

Gap: existing multilingual code-generation benchmarks emphasize short tasks,
while repository-level maintenance benchmarks often focus on a small number of
ecosystems.

Claim: like-for-like cumulative lifecycle evaluation exposes differences in
repair burden and failure modes that pass rate alone hides.

Contributions:

1. Cross-language D&D REST lifecycle benchmark and central evaluator.
2. Five-model, fifteen-target nine-stage baseline with shot-level artifacts.
3. SQLite and self-contained dashboard infrastructure for reproducible analysis.
4. Design-dimension framing and roadmap for longer inherited-codebase studies.

## Methods Slots

Subjects: five model aliases (`claude/opus`, `claude/sonnet`,
`codex/gpt-5.5`, `pi/kimi-k2p7-code`, `pi/glm-5p2`) and fifteen
language/framework targets.

Task design: identical natural-language specs, black-box HTTP conformance
checks, cumulative lifecycle stages, fresh maintenance agents, and deterministic
bug-fix prompts after evaluator failures.

Instrumentation: prompt/response capture, evaluator reports, lifecycle JSON,
SQLite experiment-state DB, and dashboard JSON/HTML.

Controls: latest runtimes/frameworks intentionally used; infrastructure blocks
classified separately; each cell isolated in its own folder/codebase.

Missing before submission: exact provider/model version metadata where
available, wall-clock/time/cost metrics, quantitative target covariates, and
statistical model specification.

## Results Slots

Primary nine-stage result: 59/75 full lifecycle passes, 16 deterministic
failures, 784 total shots.

By model: Opus 15/15, GPT 13/15, Kimi 11/15, Sonnet 10/15, GLM 10/15.

By target: `go-stdlib`, `java-stdlib`, `python-flask`, and `typescript-node`
are 5/5; several other targets show concentrated stage-specific failures.

Shot burden: clean full pass minimum is 9 shots per cell; many successful cells
take 11-15 shots.

Failure stages: `combat-state` dominates deterministic failures; exact JSON
shape and state-transition semantics are recurring issues.

## Discussion Slots

- Pass rate is insufficient for evaluating coding agents in maintenance loops.
- Compiler/type feedback is only one part of the story; exact black-box
  contract feedback also drives repair.
- Framework and ecosystem effects need quantitative covariate coding before
  strong causal claims.
- Latest-version testing is ecologically valid but increases volatility and
  may amplify post-training-cutoff mismatch.

## Threats To Validity

- Task authorship may encode domain or language preferences.
- Target covariates are not yet fully measured.
- Model aliases may change over time; runs must record exact resolved model IDs
  when possible.
- Provider CLI infrastructure can fail independently of model quality; the
  blocked classification mitigates but does not eliminate this risk.
- Results are functional only; code quality, maintainability, and security are
  not directly evaluated yet.

## Figures And Tables To Create

1. Experimental design diagram: model x target x lifecycle stage x shot.
2. Model summary table with pass rate, shots, and failed stages.
3. Target summary table with pass rate, shots, and failed stages.
4. Stage-failure histogram.
5. Shot-burden distribution for passing cells.
6. Screenshot or architecture diagram of the JSON/SQLite/dashboard artifact flow.

