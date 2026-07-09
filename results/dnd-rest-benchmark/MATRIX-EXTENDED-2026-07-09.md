# D&D REST Matrix Results: Extended 2026-07-09

Extended matrix: 5 models x 14 language/framework targets = 70 runs.

This extends [`MATRIX-2026-07-09.md`](MATRIX-2026-07-09.md) with:

- `python-flask`
- `python-django`
- `php-slim`
- `php-symfony`

## Models

- `claude/claude-opus-latest`: `claude -p --model opus`
- `claude/claude-sonnet-latest`: `claude -p --model sonnet`
- `codex/gpt-5.5-medium`: Codex CLI with `gpt-5.5`
- `pi/kimi-k2p7-code`: Pi via Fireworks, `accounts/fireworks/models/kimi-k2p7-code`
- `pi/glm-5p2`: Pi via Fireworks, `accounts/fireworks/models/glm-5p2`

## Version Pins

- `@types/node`: `26.1.1`
- `@types/react`: `19.2.17`
- `@types/react-dom`: `19.2.3`
- `@vitejs/plugin-react`: `6.0.3`
- `composer`: `2.10.2`
- `django`: `6.0.7`
- `flask`: `3.1.3`
- `go`: `1.26.5`
- `next`: `16.2.10`
- `node`: `26.4.0`
- `openjdk`: `26.0.1`
- `php`: `8.5.8`
- `puma`: `8.0.2`
- `python`: `3.14.6`
- `rack`: `3.2.6`
- `rackup`: `2.3.1`
- `rails`: `8.1.3`
- `react`: `19.2.7`
- `react-dom`: `19.2.7`
- `ruby`: `4.0.5`
- `sinatra`: `4.2.1`
- `slim`: `4.15.2`
- `slim-psr7`: `1.8.0`
- `symfony-http-foundation`: `8.1.1`
- `symfony-routing`: `8.1.0`
- `typescript`: `7.0.2`
- `vite`: `8.1.3`

## Summary

- Overall: 57/70 passed

By target:

- `go-stdlib`: 5/5
- `java-stdlib`: 3/5
- `php-slim`: 4/5
- `php-stdlib`: 5/5
- `php-symfony`: 4/5
- `python-django`: 5/5
- `python-flask`: 5/5
- `python-stdlib`: 4/5
- `ruby-rails`: 3/5
- `ruby-sinatra`: 3/5
- `ruby-stdlib`: 5/5
- `typescript-nextjs`: 2/5
- `typescript-node`: 4/5
- `typescript-vite`: 5/5

By model:

- `claude/claude-opus-latest`: 14/14
- `claude/claude-sonnet-latest`: 13/14
- `codex/gpt-5.5-medium`: 11/14
- `pi/glm-5p2`: 13/14
- `pi/kimi-k2p7-code`: 6/14

## Matrix

| Target | Opus | Sonnet | GPT-5.5 medium | Kimi K2.7 Code | GLM 5.2 |
|---|---:|---:|---:|---:|---:|
| `go-stdlib` | PASS | PASS | PASS | PASS | PASS |
| `java-stdlib` | PASS | PASS | FAIL (4/8) | FAIL (7/8) | PASS |
| `php-slim` | PASS | PASS | PASS | FAIL (7/8) | PASS |
| `php-stdlib` | PASS | PASS | PASS | PASS | PASS |
| `php-symfony` | PASS | PASS | PASS | FAIL (7/8) | PASS |
| `python-django` | PASS | PASS | PASS | PASS | PASS |
| `python-flask` | PASS | PASS | PASS | PASS | PASS |
| `python-stdlib` | PASS | PASS | PASS | FAIL (7/8) | PASS |
| `ruby-rails` | PASS | FAIL (0/0) | PASS | FAIL (7/8) | PASS |
| `ruby-sinatra` | PASS | PASS | FAIL (0/0) | FAIL (7/8) | PASS |
| `ruby-stdlib` | PASS | PASS | PASS | PASS | PASS |
| `typescript-nextjs` | PASS | PASS | FAIL (0/0) | FAIL (0/0) | FAIL (0/0) |
| `typescript-node` | PASS | PASS | PASS | FAIL (7/8) | PASS |
| `typescript-vite` | PASS | PASS | PASS | PASS | PASS |

## New Target Results

The add-on run for Flask, Django, Slim, and Symfony was 18/20 passing.

- `python-flask`: 5/5
- `python-django`: 5/5
- `php-slim`: 4/5
- `php-symfony`: 4/5

New failures:

- `pi/kimi-k2p7-code` on `php-slim`: 7/8 tests; dice-stats-1d20-minus-1 average was `10`, expected `9.5`.
- `pi/kimi-k2p7-code` on `php-symfony`: 7/8 tests; dice-stats-1d20-minus-1 average was `10`, expected `9.5`.

## Notes

- The "latest versions" design choice is now represented directly in `VERSION-PINS.json` for every run artifact.
- `typescript-vite` remained 5/5. On this first D&D REST suite, Go did not outperform Vite on pass rate; the stronger contrast is Go/stdlib 5/5 versus TypeScript/Next.js 2/5 and TypeScript/Node stdlib 4/5.
- Flask and Django both went 5/5 across all five models, which suggests this first suite is too easy for mainstream Python web stacks.
- Kimi's recurring 7/8 failure mode is consistent across several languages/frameworks: it mishandles negative dice modifiers in average calculation.
- Raw artifacts and generated implementations are under `results/dnd-rest-benchmark/runs/`.
