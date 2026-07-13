# Full Lifecycle Matrix

Data sources:

- [`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)
- [`results/dnd-rest-benchmark/experiment-state.sqlite3`](../../results/dnd-rest-benchmark/experiment-state.sqlite3)
- [`results/dnd-rest-benchmark/dnd-rest-findings.html`](../../results/dnd-rest-benchmark/dnd-rest-findings.html)

Run set: latest terminal nine-stage D&D REST lifecycle result per
model/target cell, after rerunning Claude cells with confirmed working model
selection on 2026-07-12/13.

The completed matrix contains 75 cells: 5 models by 15 language/framework
targets. Each cell attempted these cumulative stages:

1. `core`
2. `characters`
3. `combat-state`
4. `auth-users`
5. `sqlite-storage`
6. `compendium`
7. `campaign-state`
8. `phb-rules`
9. `dm-tools`

Every creative, maintenance, or bug-fix invocation counts as one shot. A clean
full lifecycle pass therefore requires 9 shots. Extra shots are deterministic
bug-fix attempts after evaluator failures.

## Overall

| Metric | Value |
| --- | ---: |
| Matrix cells | 75 |
| Full lifecycle passes | 59 |
| Deterministic failed lifecycle cells | 16 |
| Overall pass rate | 78.7% |
| Completed stages | 575/675 |
| Total shots | 784 |
| Minimum shots if all cells were clean passes | 675 |
| Extra shots beyond clean-pass minimum | 109 |

## By Model

| Model | Pass rate | Failed stages | Avg shots/cell | Avg shots/pass |
| --- | ---: | --- | ---: | ---: |
| `claude/opus` | 15/15 | none | 11.27 | 11.27 |
| `codex/gpt-5.5` | 13/15 | `combat-state` x2 | 10.80 | 11.85 |
| `pi/kimi-k2p7-code` | 11/15 | `combat-state` x3, `auth-users` | 10.80 | 12.91 |
| `claude/sonnet` | 10/15 | `combat-state` x2, `dm-tools`, `compendium`, `campaign-state` | 10.60 | 12.00 |
| `pi/glm-5p2` | 10/15 | `combat-state` x4, `core` | 8.80 | 11.30 |

## By Target

| Target | Pass rate | Avg shots/cell | Avg shots/pass | Failed stages |
| --- | ---: | ---: | ---: | --- |
| `go-stdlib` | 5/5 | 11.60 | 11.60 | none |
| `java-stdlib` | 5/5 | 12.00 | 12.00 | none |
| `python-flask` | 5/5 | 12.00 | 12.00 | none |
| `typescript-node` | 5/5 | 12.00 | 12.00 | none |
| `php-slim` | 4/5 | 10.00 | 11.50 | `combat-state` |
| `php-symfony` | 4/5 | 9.80 | 11.25 | `combat-state` |
| `python-django` | 4/5 | 11.60 | 11.25 | `dm-tools` |
| `python-stdlib` | 4/5 | 10.80 | 12.50 | `combat-state` |
| `ruby-rails` | 4/5 | 10.60 | 12.75 | `core` |
| `ruby-stdlib` | 4/5 | 11.00 | 11.50 | `compendium` |
| `typescript-vite` | 4/5 | 10.60 | 12.00 | `combat-state` |
| `php-stdlib` | 3/5 | 8.40 | 11.33 | `combat-state` x2 |
| `rust-stdlib` | 3/5 | 8.60 | 11.67 | `combat-state` x2 |
| `typescript-nextjs` | 3/5 | 9.00 | 12.33 | `combat-state` x2 |
| `ruby-sinatra` | 2/5 | 8.80 | 11.50 | `campaign-state`, `auth-users`, `combat-state` |

## Claude Rerun Correction

Earlier Claude results were confounded by CLI session/quota/auth blocks and by
ambiguous model alias behavior. Those shots remain preserved in the artifact
tree and classified separately in
[`003-infra-block-classification.md`](003-infra-block-classification.md), but
they are not treated as comparative model failures in the latest matrix above.

After verifying `claude -p --model` behavior and rerunning:

| Model | Latest result | Shots | Note |
| --- | ---: | ---: | --- |
| `claude/opus` | 15/15 | 169 | Green on every target, but never clean-nine-shot; every pass required at least one repair or maintenance overhead shot. |
| `claude/sonnet` | 10/15 | 159 | Strong on many targets but retained deterministic failures on five cells. |

## Failure Patterns

`combat-state` is the dominant deterministic failure stage across non-passing
cells. The most common exact issue is response-shape drift after a condition
expires: implementations return an empty `conditions` object instead of keeping
the target key with an empty array, e.g. `"fighter": []`.

`auth-users` failures are usually exact-status failures, especially returning
`200` where the evaluator requires `201` for user registration.

Late maintenance failures are more varied. Examples include missing or empty
`open_threads` in `dm-tools`, campaign state regressions in inherited apps, and
compendium persistence/lookup mismatches.

## Interpretation

The main empirical result is that pass rate alone is incomplete. The strongest
model, latest Opus, passed every cell but took 169 shots across 15 cells: 34
extra shots beyond the clean 135-shot minimum. Successful cells routinely took
11-15 shots, so shot burden and stage of first failure should be primary
outcomes alongside pass/fail.

The target effect is visible but not reducible to a single language ranking.
Four targets were green across every model (`go-stdlib`, `java-stdlib`,
`python-flask`, `typescript-node`), while several framework/runtime targets
showed one or more stage-specific failures. The next analysis step is to code
design dimensions quantitatively and test whether those dimensions explain
shot burden and failure stage after controlling for model and task effects.

The benchmark should now move from nine-stage comparison to the longer
16-stage roadmap: one initial creative build plus 15 fresh maintenance
inheritances. That longer run is the better instrument for studying what
happens as inherited codebases grow.

## Follow-Up Questions

- Add normalized retry metrics by stage, not only by cell.
- Add per-stage wall-clock time and token/cost estimates where providers expose them.
- Quantify target covariates: dependency count, package age/churn, formatter/linter canonicalization, framework count per task category, and corpus prevalence.
- Run the 16-stage lifecycle after this nine-stage baseline is frozen.
- Add seeded debugging/refactor strata without mixing them directly into the greenfield lifecycle score.
