# Results To Date

Data source:
[`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)

As of the stored 2026-07-09/2026-07-10 lifecycle run set, the benchmark contains
70 completed matrix cells: 5 models by 14 language/framework targets. Each cell
ran the first three cumulative stages: `core`, `characters`, and
`combat-state`.

## Overall

| Metric | Value |
| --- | ---: |
| Matrix cells | 70 |
| Passing cells | 54 |
| Failing cells | 16 |
| Total shots | 281 |
| Average shots per cell | 4.01 |
| Shots in passing cells | 228 |
| Average shots per passing cell | 4.22 |

The minimum passing run requires 3 shots: one creative stage plus two
maintenance stages. Passing cells averaged 4.22 shots, or 1.22 extra bug-fix
shots beyond the minimum.

## By Target

| Target | Pass rate | Total shots | Avg shots/cell | Avg shots/passing cell |
| --- | ---: | ---: | ---: | ---: |
| `go-stdlib` | 5/5 | 22 | 4.40 | 4.40 |
| `java-stdlib` | 3/5 | 20 | 4.00 | 4.67 |
| `php-slim` | 2/5 | 22 | 4.40 | 4.50 |
| `php-stdlib` | 3/5 | 21 | 4.20 | 4.33 |
| `php-symfony` | 3/5 | 20 | 4.00 | 4.00 |
| `python-django` | 5/5 | 21 | 4.20 | 4.20 |
| `python-flask` | 4/5 | 20 | 4.00 | 4.00 |
| `python-stdlib` | 5/5 | 19 | 3.80 | 3.80 |
| `ruby-rails` | 5/5 | 23 | 4.60 | 4.60 |
| `ruby-sinatra` | 3/5 | 19 | 3.80 | 5.00 |
| `ruby-stdlib` | 2/5 | 17 | 3.40 | 4.50 |
| `typescript-nextjs` | 4/5 | 18 | 3.60 | 4.00 |
| `typescript-node` | 5/5 | 20 | 4.00 | 4.00 |
| `typescript-vite` | 5/5 | 19 | 3.80 | 3.80 |

## By Model

| Model | Pass rate | Total shots | Avg shots/cell | Avg shots/passing cell |
| --- | ---: | ---: | ---: | ---: |
| `claude/opus` | 10/14 | 52 | 3.71 | 4.00 |
| `claude/sonnet` | 9/14 | 47 | 3.36 | 3.67 |
| `codex/gpt-5.5` | 12/14 | 58 | 4.14 | 4.17 |
| `pi/glm-5p2` | 12/14 | 62 | 4.43 | 4.50 |
| `pi/kimi-k2p7-code` | 11/14 | 62 | 4.43 | 4.64 |

## Stage Outcomes

| Stage | Passing attempts | Total attempts |
| --- | ---: | ---: |
| `core` | 64 | 70 |
| `characters` | 64 | 64 |
| `combat-state` | 54 | 64 |

Failure stage counts:

| Failed stage | Cells |
| --- | ---: |
| `core` | 6 |
| `combat-state` | 10 |

## Early Interpretation

The first matrix does not yet show Go dominating TypeScript across the board.
`go-stdlib`, `typescript-node`, and `typescript-vite` all passed 5/5 cells, and
`typescript-vite` did so with fewer average shots than `go-stdlib` on this
three-stage suite. That is useful rather than fatal: the current tasks may not
yet apply enough codebase-growth, persistence, dependency-churn, or implicitness
pressure to expose the hypothesized advantage.

The new roadmap stages intentionally increase those pressures. SQLite storage,
campaign state, compendium data, and bundled DM features should make codebase
maintenance, framework conventions, schema drift, and hidden dependency
behavior more visible.

Ruby Rails was surprisingly strong on pass rate, but retry-heavy. Ruby stdlib
and Sinatra were weaker. PHP targets varied substantially by framework. The
combat-state stage is the current stress point, especially around multi-request
state and exact JSON response shape.

