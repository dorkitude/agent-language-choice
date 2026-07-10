# 008 Selected PHB Rules

Status: specified; evaluator suite added.

Spec: [`challenges/phb-rules.md`](../../experiments/dnd-rest-benchmark/challenges/phb-rules.md)  
Evaluator suite: `phb-rules`

## Request

Add selected Player's Handbook-style deterministic rule helpers.

## Required Behaviors

- `POST /v1/phb/spell-slots`
- `POST /v1/phb/rests/long`
- `POST /v1/phb/equipment-load`
- Return deterministic spell slot maps, long-rest state changes, and carrying
  capacity/encumbrance results

## Prompt Role

Maintenance agent.

## Scoring Notes

This stage combines domain rule recall with JSON shape discipline. It tests
whether agents can add tables/rules without over-generalizing or importing a
large library that may not match the evaluator contract.

