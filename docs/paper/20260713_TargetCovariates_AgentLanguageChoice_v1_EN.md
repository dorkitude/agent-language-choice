# Target Covariate Coding Plan

Version: v1. Date: 2026-07-13.

Purpose: convert the qualitative target matrix in `RESEARCH-DESIGN.md` into
paper-ready variables for analysis. These are coding instructions, not final
measured values.

## Unit

One row per benchmark target:

`go-stdlib`, `rust-stdlib`, `java-stdlib`, `typescript-node`,
`typescript-vite`, `typescript-nextjs`, `python-stdlib`, `python-flask`,
`python-django`, `ruby-stdlib`, `ruby-sinatra`, `ruby-rails`, `php-stdlib`,
`php-slim`, `php-symfony`.

## Proposed Columns

| Column | Type | Definition |
| --- | --- | --- |
| `target` | string | Harness target id. |
| `language` | categorical | Programming language. |
| `framework` | categorical | Framework/runtime label. |
| `compiled_aot` | binary | 1 if the normal target build/run includes ahead-of-time compilation before serving requests. |
| `static_typecheck_signal` | ordinal 0-3 | 0 none, 1 optional/weak, 2 strong but not always enforced, 3 strong and enforced by build. |
| `zero_dep_possible` | binary | 1 if the target can satisfy all benchmark stages with no third-party packages beyond the language runtime. |
| `dependency_count_generated` | integer | Number of third-party dependencies in the generated terminal codebase. Compute from each run where possible; aggregate by target/model. |
| `framework_weight` | ordinal 0-3 | 0 stdlib, 1 light microframework, 2 component framework, 3 full-stack/convention-heavy framework. |
| `implicitness_risk` | ordinal 0-3 | Hidden behavior risk from autoloading, monkey-patching, decorators/metaprogramming, DI, convention routing, structural typing edge cases. |
| `idiom_uniformity` | ordinal 0-3 | Degree of canonical style/tooling and low variance in mainstream implementation patterns. |
| `latest_version_churn_risk` | ordinal 0-3 | Expected mismatch risk from latest runtime/framework versions and recent breaking changes. |
| `corpus_prevalence_proxy` | ordinal 0-3 | Approximate public-code prevalence for the language/framework. Replace with measured data if available. |
| `startup_complexity` | ordinal 0-3 | Amount of harness-specific ceremony needed to start a compliant server. |

## Coding Rules

- Prefer measured values over subjective labels.
- For subjective ordinal columns, keep a short rationale and cite a source or
  artifact observation.
- Have at least two coders independently score subjective columns before
  submission; resolve disagreements in a logged adjudication file.
- Run sensitivity checks with subjective covariates removed or binarized.

## Analysis Hooks

Outcome variables from SQLite/JSON:

- `passed`
- `completed_stages`
- `total_shots`
- `failed_stage`
- per-shot `shot_kind`
- per-shot `agent_exit_class`

Candidate models:

- Logistic mixed-effects model: `passed ~ covariates + (1|model)`.
- Count model for shot burden among passes: `total_shots - 9 ~ covariates + (1|model)`.
- Discrete-time survival or ordinal model for failure stage among failures.
- Sensitivity analysis excluding infrastructure-blocked historical runs and
  using only latest terminal cells.

