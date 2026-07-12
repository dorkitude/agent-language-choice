# Full Lifecycle Matrix

Data source:
[`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)

Run set: 2026-07-10 through 2026-07-12 D&D REST lifecycle benchmark.

The completed matrix contains 75 cells: 5 models by 15 language/framework targets. Each cell attempted the nine cumulative lifecycle stages:

1. `core`
2. `characters`
3. `combat-state`
4. `auth-users`
5. `sqlite-storage`
6. `compendium`
7. `campaign-state`
8. `phb-rules`
9. `dm-tools`

Every creative, maintenance, or bug-fix invocation counts as one shot. A clean full lifecycle pass therefore requires 9 shots. Extra shots are deterministic bug-fix attempts after evaluator failures.

## Overall

| Metric | Value |
| --- | ---: |
| Matrix cells | 75 |
| Full lifecycle passes | 41 |
| Failed lifecycle cells | 34 |
| Overall pass rate | 54.7% |
| Total shots | 635 |

## By Model

| Model | Pass rate | Failed stages | Avg shots/cell | Avg shots/pass |
| --- | ---: | --- | ---: | ---: |
| `codex/gpt-5.5` | 13/15 | `combat-state` x2 | 10.80 | 11.85 |
| `pi/kimi-k2p7-code` | 11/15 | `auth-users`, `combat-state` x3 | 10.80 | 12.91 |
| `pi/glm-5p2` | 10/15 | `combat-state` x4, `core` | 8.80 | 11.30 |
| `claude/opus` | 5/15 | `auth-users` x2, `compendium`, `core` x6, `dm-tools` | 6.80 | 11.40 |
| `claude/sonnet` | 2/15 | `campaign-state`, `core` x10, `dm-tools`, `phb-rules` | 5.13 | 11.50 |

## By Target

| Target | Pass rate | Avg shots/cell | Avg shots/pass | Failed stages |
| --- | ---: | ---: | ---: | --- |
| `php-symfony` | 4/5 | 9.80 | 11.25 | `combat-state` |
| `python-django` | 4/5 | 11.60 | 11.25 | `dm-tools` |
| `typescript-vite` | 4/5 | 10.60 | 12.00 | `combat-state` |
| `go-stdlib` | 3/5 | 10.20 | 12.33 | `core`, `dm-tools` |
| `java-stdlib` | 3/5 | 9.00 | 12.33 | `auth-users`, `core` |
| `python-flask` | 3/5 | 8.20 | 12.33 | `core` x2 |
| `ruby-stdlib` | 3/5 | 7.80 | 11.67 | `core` x2 |
| `typescript-node` | 3/5 | 8.00 | 12.00 | `core` x2 |
| `php-slim` | 2/5 | 6.20 | 11.50 | `combat-state`, `core` x2 |
| `php-stdlib` | 2/5 | 6.20 | 11.50 | `combat-state`, `core` x2 |
| `python-stdlib` | 2/5 | 6.60 | 12.50 | `combat-state`, `core` x2 |
| `ruby-rails` | 2/5 | 8.20 | 14.00 | `compendium`, `core` x2 |
| `ruby-sinatra` | 2/5 | 8.80 | 11.50 | `auth-users`, `campaign-state`, `combat-state` |
| `rust-stdlib` | 2/5 | 8.40 | 11.00 | `combat-state` x2, `phb-rules` |
| `typescript-nextjs` | 2/5 | 7.40 | 12.50 | `auth-users`, `combat-state`, `core` |

## Model x Target Outcomes

| Model | Target | Outcome | Shots | Failed stage |
| --- | --- | --- | ---: | --- |
| `glm-5p2` | `go-stdlib` | PASS | 13 |  |
| `glm-5p2` | `java-stdlib` | PASS | 11 |  |
| `glm-5p2` | `php-slim` | PASS | 11 |  |
| `glm-5p2` | `php-stdlib` | PASS | 10 |  |
| `glm-5p2` | `php-symfony` | PASS | 11 |  |
| `glm-5p2` | `python-django` | PASS | 11 |  |
| `glm-5p2` | `python-flask` | PASS | 11 |  |
| `glm-5p2` | `python-stdlib` | FAIL | 4 | `combat-state` |
| `glm-5p2` | `ruby-rails` | FAIL | 2 | `core` |
| `glm-5p2` | `ruby-sinatra` | FAIL | 5 | `combat-state` |
| `glm-5p2` | `ruby-stdlib` | PASS | 12 |  |
| `glm-5p2` | `rust-stdlib` | FAIL | 4 | `combat-state` |
| `glm-5p2` | `typescript-nextjs` | FAIL | 4 | `combat-state` |
| `glm-5p2` | `typescript-node` | PASS | 11 |  |
| `glm-5p2` | `typescript-vite` | PASS | 12 |  |
| `gpt-5.5` | `go-stdlib` | PASS | 12 |  |
| `gpt-5.5` | `java-stdlib` | PASS | 11 |  |
| `gpt-5.5` | `php-slim` | FAIL | 4 | `combat-state` |
| `gpt-5.5` | `php-stdlib` | FAIL | 4 | `combat-state` |
| `gpt-5.5` | `php-symfony` | PASS | 12 |  |
| `gpt-5.5` | `python-django` | PASS | 11 |  |
| `gpt-5.5` | `python-flask` | PASS | 12 |  |
| `gpt-5.5` | `python-stdlib` | PASS | 12 |  |
| `gpt-5.5` | `ruby-rails` | PASS | 14 |  |
| `gpt-5.5` | `ruby-sinatra` | PASS | 12 |  |
| `gpt-5.5` | `ruby-stdlib` | PASS | 11 |  |
| `gpt-5.5` | `rust-stdlib` | PASS | 11 |  |
| `gpt-5.5` | `typescript-nextjs` | PASS | 13 |  |
| `gpt-5.5` | `typescript-node` | PASS | 12 |  |
| `gpt-5.5` | `typescript-vite` | PASS | 11 |  |
| `kimi-k2p7-code` | `go-stdlib` | PASS | 12 |  |
| `kimi-k2p7-code` | `java-stdlib` | PASS | 15 |  |
| `kimi-k2p7-code` | `php-slim` | PASS | 12 |  |
| `kimi-k2p7-code` | `php-stdlib` | PASS | 13 |  |
| `kimi-k2p7-code` | `php-symfony` | FAIL | 4 | `combat-state` |
| `kimi-k2p7-code` | `python-django` | PASS | 12 |  |
| `kimi-k2p7-code` | `python-flask` | PASS | 14 |  |
| `kimi-k2p7-code` | `python-stdlib` | PASS | 13 |  |
| `kimi-k2p7-code` | `ruby-rails` | PASS | 14 |  |
| `kimi-k2p7-code` | `ruby-sinatra` | FAIL | 7 | `auth-users` |
| `kimi-k2p7-code` | `ruby-stdlib` | PASS | 12 |  |
| `kimi-k2p7-code` | `rust-stdlib` | FAIL | 4 | `combat-state` |
| `kimi-k2p7-code` | `typescript-nextjs` | PASS | 12 |  |
| `kimi-k2p7-code` | `typescript-node` | PASS | 13 |  |
| `kimi-k2p7-code` | `typescript-vite` | FAIL | 5 | `combat-state` |
| `opus` | `go-stdlib` | FAIL | 12 | `dm-tools` |
| `opus` | `java-stdlib` | FAIL | 6 | `auth-users` |
| `opus` | `php-slim` | FAIL | 2 | `core` |
| `opus` | `php-stdlib` | FAIL | 2 | `core` |
| `opus` | `php-symfony` | PASS | 11 |  |
| `opus` | `python-django` | PASS | 11 |  |
| `opus` | `python-flask` | FAIL | 2 | `core` |
| `opus` | `python-stdlib` | FAIL | 2 | `core` |
| `opus` | `ruby-rails` | FAIL | 9 | `compendium` |
| `opus` | `ruby-sinatra` | PASS | 11 |  |
| `opus` | `ruby-stdlib` | FAIL | 2 | `core` |
| `opus` | `rust-stdlib` | PASS | 11 |  |
| `opus` | `typescript-nextjs` | FAIL | 6 | `auth-users` |
| `opus` | `typescript-node` | FAIL | 2 | `core` |
| `opus` | `typescript-vite` | PASS | 13 |  |
| `sonnet` | `go-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `java-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `php-slim` | FAIL | 2 | `core` |
| `sonnet` | `php-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `php-symfony` | PASS | 11 |  |
| `sonnet` | `python-django` | FAIL | 13 | `dm-tools` |
| `sonnet` | `python-flask` | FAIL | 2 | `core` |
| `sonnet` | `python-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `ruby-rails` | FAIL | 2 | `core` |
| `sonnet` | `ruby-sinatra` | FAIL | 9 | `campaign-state` |
| `sonnet` | `ruby-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `rust-stdlib` | FAIL | 12 | `phb-rules` |
| `sonnet` | `typescript-nextjs` | FAIL | 2 | `core` |
| `sonnet` | `typescript-node` | FAIL | 2 | `core` |
| `sonnet` | `typescript-vite` | PASS | 12 |  |

## Rust Append Run

Rust was added append-only after the 14-target baseline. It was intentionally constrained to Rust 1.97.0 with standard-library-only HTTP and JSON handling. That makes it a strong compiler-signal comparator, but not an ergonomic web-framework comparator.

| Model | Outcome | Shots | Failed stage | Completed stages |
| --- | --- | ---: | --- | ---: |
| `glm-5p2` | FAIL | 4 | `combat-state` | 2/9 |
| `gpt-5.5` | PASS | 11 |  | 9/9 |
| `kimi-k2p7-code` | FAIL | 4 | `combat-state` | 2/9 |
| `opus` | PASS | 11 |  | 9/9 |
| `sonnet` | FAIL | 12 | `phb-rules` | 7/9 |

Result: `rust-stdlib` passed for `opus` and `gpt-5.5`, both in 11 shots. It failed for `sonnet` at `phb-rules` after 12 shots, and failed for both open-weight models at `combat-state` after 4 shots.

## Interpretation

This full lifecycle suite still does not support a broad claim that Go is easier for coding agents than TypeScript. `typescript-vite` remains stronger than `go-stdlib` on pass count, and `gpt-5.5` completed every TypeScript target. The original Go-over-Vite signal remains model-specific: `kimi-k2p7-code` passed Go while failing Vite at `combat-state`.

The stronger empirical contrast is now Ruby/Rails and Rust/Go as different kinds of explicitness stress tests. Ruby/Rails continues to be a sharp foil for convention-heavy and dynamically resolved semantics: `ruby-rails` passed 2/5 and both passes required 14 shots; `ruby-sinatra` passed 2/5 and failed at three different later stages. Rust adds an explicit compiled target, but stdlib-only HTTP/JSON makes it ergonomically hard: strong proprietary models passed, while Kimi and GLM failed at combat-state.

The cost side strongly supports the codebase-growth thesis. A perfect lifecycle would take 9 shots, but many successful cells took 11 to 15 shots. Pass rate alone is therefore incomplete; shot burden and failed stage are first-class results.

The model effect remains large. `gpt-5.5` is strongest overall at 13/15. The open-weight models are competitive but show Rust-specific weakness. The Claude CLI cells are uneven: Opus passed Rust but failed many other targets, and Sonnet failed most cells. That should be investigated as a harness/model-interface confound before drawing language-design conclusions from Claude failures.

## Follow-Up Questions

- Inspect failure artifacts for Claude early `core` failures to determine whether they are prompt/harness issues or genuine implementation failures.
- Add normalized retry metrics by stage, not only by cell.
- Add per-stage wall-clock time and token/cost estimates where providers expose them.
- Add tasks that more directly stress API churn, hidden imports, dependency version mismatch, and implicit framework behavior.
- Re-run selected cells with more fix shots to separate "cannot solve" from "needs more repair attempts."
