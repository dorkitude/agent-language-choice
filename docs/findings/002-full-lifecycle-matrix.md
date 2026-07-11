# Full Lifecycle Matrix

Data source:
[`results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)

Run set: 2026-07-10/2026-07-11 D&D REST lifecycle benchmark.

The completed matrix contains 70 cells: 5 models by 14 language/framework
targets. Each cell attempted the nine cumulative lifecycle stages:

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
| Matrix cells | 70 |
| Full lifecycle passes | 39 |
| Failed lifecycle cells | 31 |
| Overall pass rate | 55.7% |

## By Model

| Model | Pass rate | Failed stages | Avg shots/cell | Avg shots/pass |
| --- | ---: | --- | ---: | ---: |
| `codex/gpt-5.5` | 12/14 | `php-stdlib:combat-state`, `php-slim:combat-state` | 10.79 | 11.92 |
| `pi/kimi-k2p7-code` | 11/14 | `typescript-vite:combat-state`, `ruby-sinatra:auth-users`, `php-symfony:combat-state` | 11.29 | 12.91 |
| `pi/glm-5p2` | 10/14 | `typescript-nextjs:combat-state`, `python-stdlib:combat-state`, `ruby-sinatra:combat-state`, `ruby-rails:core` | 9.14 | 11.30 |
| `claude/opus` | 4/14 | 10 failures, mostly early `core`; late failures on `go-stdlib:dm-tools` and `ruby-rails:compendium` | 6.50 | 11.50 |
| `claude/sonnet` | 2/14 | 12 failures, mostly early `core`; late failures on `python-django:dm-tools` and `ruby-sinatra:campaign-state` | 4.64 | 11.50 |

## By Target

| Target | Pass rate | Avg shots/cell | Avg shots/pass | Failed stages |
| --- | ---: | ---: | ---: | --- |
| `python-django` | 4/5 | 11.60 | 11.25 | `dm-tools` |
| `php-symfony` | 4/5 | 9.80 | 11.25 | `combat-state` |
| `typescript-vite` | 4/5 | 10.60 | 12.00 | `combat-state` |
| `go-stdlib` | 3/5 | 10.20 | 12.33 | `dm-tools`, `core` |
| `java-stdlib` | 3/5 | 9.00 | 12.33 | `auth-users`, `core` |
| `python-flask` | 3/5 | 8.20 | 12.33 | `core` x2 |
| `ruby-stdlib` | 3/5 | 7.80 | 11.67 | `core` x2 |
| `typescript-node` | 3/5 | 8.00 | 12.00 | `core` x2 |
| `php-stdlib` | 2/5 | 6.20 | 11.50 | `core` x2, `combat-state` |
| `php-slim` | 2/5 | 6.20 | 11.50 | `core` x2, `combat-state` |
| `python-stdlib` | 2/5 | 6.60 | 12.50 | `core` x2, `combat-state` |
| `ruby-rails` | 2/5 | 8.20 | 14.00 | `core` x2, `compendium` |
| `ruby-sinatra` | 2/5 | 8.80 | 11.50 | `combat-state`, `auth-users`, `campaign-state` |
| `typescript-nextjs` | 2/5 | 7.40 | 12.50 | `core`, `auth-users`, `combat-state` |

## Model x Target Outcomes

| Model | Target | Outcome | Shots | Failed stage |
| --- | --- | --- | ---: | --- |
| `glm-5p2` | `go-stdlib` | PASS | 13 | |
| `glm-5p2` | `java-stdlib` | PASS | 11 | |
| `glm-5p2` | `php-slim` | PASS | 11 | |
| `glm-5p2` | `php-stdlib` | PASS | 10 | |
| `glm-5p2` | `php-symfony` | PASS | 11 | |
| `glm-5p2` | `python-django` | PASS | 11 | |
| `glm-5p2` | `python-flask` | PASS | 11 | |
| `glm-5p2` | `python-stdlib` | FAIL | 4 | `combat-state` |
| `glm-5p2` | `ruby-rails` | FAIL | 2 | `core` |
| `glm-5p2` | `ruby-sinatra` | FAIL | 5 | `combat-state` |
| `glm-5p2` | `ruby-stdlib` | PASS | 12 | |
| `glm-5p2` | `typescript-nextjs` | FAIL | 4 | `combat-state` |
| `glm-5p2` | `typescript-node` | PASS | 11 | |
| `glm-5p2` | `typescript-vite` | PASS | 12 | |
| `gpt-5.5` | `go-stdlib` | PASS | 12 | |
| `gpt-5.5` | `java-stdlib` | PASS | 11 | |
| `gpt-5.5` | `php-slim` | FAIL | 4 | `combat-state` |
| `gpt-5.5` | `php-stdlib` | FAIL | 4 | `combat-state` |
| `gpt-5.5` | `php-symfony` | PASS | 12 | |
| `gpt-5.5` | `python-django` | PASS | 11 | |
| `gpt-5.5` | `python-flask` | PASS | 12 | |
| `gpt-5.5` | `python-stdlib` | PASS | 12 | |
| `gpt-5.5` | `ruby-rails` | PASS | 14 | |
| `gpt-5.5` | `ruby-sinatra` | PASS | 12 | |
| `gpt-5.5` | `ruby-stdlib` | PASS | 11 | |
| `gpt-5.5` | `typescript-nextjs` | PASS | 13 | |
| `gpt-5.5` | `typescript-node` | PASS | 12 | |
| `gpt-5.5` | `typescript-vite` | PASS | 11 | |
| `kimi-k2p7-code` | `go-stdlib` | PASS | 12 | |
| `kimi-k2p7-code` | `java-stdlib` | PASS | 15 | |
| `kimi-k2p7-code` | `php-slim` | PASS | 12 | |
| `kimi-k2p7-code` | `php-stdlib` | PASS | 13 | |
| `kimi-k2p7-code` | `php-symfony` | FAIL | 4 | `combat-state` |
| `kimi-k2p7-code` | `python-django` | PASS | 12 | |
| `kimi-k2p7-code` | `python-flask` | PASS | 14 | |
| `kimi-k2p7-code` | `python-stdlib` | PASS | 13 | |
| `kimi-k2p7-code` | `ruby-rails` | PASS | 14 | |
| `kimi-k2p7-code` | `ruby-sinatra` | FAIL | 7 | `auth-users` |
| `kimi-k2p7-code` | `ruby-stdlib` | PASS | 12 | |
| `kimi-k2p7-code` | `typescript-nextjs` | PASS | 12 | |
| `kimi-k2p7-code` | `typescript-node` | PASS | 13 | |
| `kimi-k2p7-code` | `typescript-vite` | FAIL | 5 | `combat-state` |
| `opus` | `go-stdlib` | FAIL | 12 | `dm-tools` |
| `opus` | `java-stdlib` | FAIL | 6 | `auth-users` |
| `opus` | `php-slim` | FAIL | 2 | `core` |
| `opus` | `php-stdlib` | FAIL | 2 | `core` |
| `opus` | `php-symfony` | PASS | 11 | |
| `opus` | `python-django` | PASS | 11 | |
| `opus` | `python-flask` | FAIL | 2 | `core` |
| `opus` | `python-stdlib` | FAIL | 2 | `core` |
| `opus` | `ruby-rails` | FAIL | 9 | `compendium` |
| `opus` | `ruby-sinatra` | PASS | 11 | |
| `opus` | `ruby-stdlib` | FAIL | 2 | `core` |
| `opus` | `typescript-nextjs` | FAIL | 6 | `auth-users` |
| `opus` | `typescript-node` | FAIL | 2 | `core` |
| `opus` | `typescript-vite` | PASS | 13 | |
| `sonnet` | `go-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `java-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `php-slim` | FAIL | 2 | `core` |
| `sonnet` | `php-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `php-symfony` | PASS | 11 | |
| `sonnet` | `python-django` | FAIL | 13 | `dm-tools` |
| `sonnet` | `python-flask` | FAIL | 2 | `core` |
| `sonnet` | `python-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `ruby-rails` | FAIL | 2 | `core` |
| `sonnet` | `ruby-sinatra` | FAIL | 9 | `campaign-state` |
| `sonnet` | `ruby-stdlib` | FAIL | 2 | `core` |
| `sonnet` | `typescript-nextjs` | FAIL | 2 | `core` |
| `sonnet` | `typescript-node` | FAIL | 2 | `core` |
| `sonnet` | `typescript-vite` | PASS | 12 | |

## Interpretation

This full lifecycle suite does not yet support a broad claim that Go is easier
for coding agents than TypeScript. `typescript-vite` passed 4/5 cells while
`go-stdlib` passed 3/5. The one direct Go-over-Vite contrast is
`kimi-k2p7-code`: Go passed in 12 shots while Vite failed at `combat-state` in
5 shots. For `gpt-5.5`, both passed and Vite used one fewer shot. For `glm-5p2`,
both passed and Vite again used one fewer shot. For both Claude models, Vite
passed where Go failed.

The strongest current signal is not language family alone. It is the
interaction between model, framework, and the accumulated maintenance backlog.
Frameworks sometimes help by giving the model a well-known shape to follow:
`php-symfony` passed 4/5 while `php-stdlib` and `php-slim` passed 2/5. The same
effect appears in Python, where `python-django` passed 4/5 and `python-stdlib`
passed 2/5. This complicates a simple "stdlib beats framework churn" story.

The cost side still supports the codebase-growth thesis. Full passes required
11 to 15 shots in many cells, not just the 9-shot ideal. Ruby Rails is the
clearest example: it passed for GPT and Kimi, but both required 14 shots. That
suggests expressive or convention-heavy frameworks can be viable for strong
models while still imposing higher repair cost.

The proprietary model result is also uneven. `gpt-5.5` is strongest overall at
12/14. The Claude CLI cells are unexpectedly weak on this harness, especially
on early `core` failures. That should be treated as an empirical result to
investigate, not yet a language-design conclusion; prompt format, CLI behavior,
allowed tools, and timeout behavior may be confounds.

## Follow-Up Questions

- Inspect failure artifacts for Claude early `core` failures to determine
  whether they are prompt/harness issues or genuine implementation failures.
- Add normalized retry metrics by stage, not only by cell.
- Add per-stage wall-clock time and token/cost estimates where providers expose
  them.
- Add tasks that more directly stress API churn, hidden imports, dependency
  version mismatch, and implicit framework behavior.
- Re-run with more fix shots to separate "cannot solve" from "needs more repair
  attempts."
