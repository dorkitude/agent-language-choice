# 005 SQLite Persistence

Status: specified; evaluator suite added.

Spec: [`challenges/sqlite-storage.md`](../../experiments/dnd-rest-benchmark/challenges/sqlite-storage.md)  
Evaluator suite: `sqlite-storage`

## Request

Move durable game-world and state storage behind SQLite-backed APIs. Each
solution should initialize `game.db` on startup and provide deterministic
storage health/reset endpoints.

## Required Behaviors

- Create or migrate a SQLite schema on startup
- `GET /v1/storage/status`
- `POST /v1/storage/reset`
- Keep prior auth, combat, character, and core APIs passing

## Prompt Role

Maintenance agent.

## Scoring Notes

This stage deliberately moves beyond in-memory toy services. It should
differentiate ecosystems by their standard-library coverage and dependency
friction. Go and Python have SQLite paths that are typically explicit; web
framework stacks may introduce package/version churn or hidden configuration.

