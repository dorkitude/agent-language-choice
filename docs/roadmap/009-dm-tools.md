# 009 DM-Facing Helpers

Status: specified; evaluator suite added.

Spec: [`challenges/dm-tools.md`](../../experiments/dnd-rest-benchmark/challenges/dm-tools.md)  
Evaluator suite: `dm-tools`

## Request

Add Dungeon Master helper APIs on top of the stored campaign and compendium
data.

## Required Behaviors

- `POST /v1/dm/encounter-builder`
- `POST /v1/dm/loot-parcel`
- `POST /v1/dm/session-recap`
- Use stored campaign/compendium concepts where applicable
- Return deterministic encounter, loot, and recap payloads

## Prompt Role

Maintenance agent.

## Scoring Notes

This stage is intentionally bundled: it asks for multiple related product
features at once, simulating realistic backlog work. It should increase the
difference between explicit codebases with local semantics and framework-heavy
codebases where behavior is spread across conventions, autoloading, plugins,
or generated files.

