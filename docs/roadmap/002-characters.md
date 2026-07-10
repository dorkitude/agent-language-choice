# 002 Character Rules

Status: completed in the first lifecycle matrix.

Spec: [`challenges/characters.md`](../../experiments/dnd-rest-benchmark/challenges/characters.md)  
Evaluator suite: `characters`

## Request

A fresh maintenance agent inherits the passing core service and adds
character-rule endpoints while preserving all core behavior.

## Required Behaviors

- Ability modifier calculation, including negative half-floor behavior
- Proficiency bonus by level
- Derived stats from abilities, armor, shield use, and level

## Prompt Role

Maintenance agent:

```text
You are a fresh maintenance agent inheriting this existing codebase. Add the
requested feature stage while preserving all existing API behavior.
```

## Scoring Notes

This stage starts the codebase-growth pressure: agents must understand existing
routing and JSON conventions before adding new endpoints. The primary failure
mode is localized arithmetic correctness, especially negative modifiers and
derived armor/hit-point calculations.

