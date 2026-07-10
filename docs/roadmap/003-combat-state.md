# 003 Stateful Combat Sessions

Status: completed in the first lifecycle matrix.

Spec: [`challenges/combat-state.md`](../../experiments/dnd-rest-benchmark/challenges/combat-state.md)  
Evaluator suite: `combat-state`

## Request

A fresh maintenance agent inherits the character-capable service and adds
stateful combat sessions.

## Required Behaviors

- Create a combat session with deterministic initiative order
- Add named conditions to combatants
- Advance turns and rounds
- Decrement condition durations on the affected combatant's turns
- Remove expired conditions while preserving the expected JSON shape

## Prompt Role

Maintenance agent, using the same template as stage 002.

## Scoring Notes

This stage introduces mutable process state and multi-request evaluator
sequences. Most failures to date occur here or before stage 001 completes.
Observed combat failures often involve condition duration semantics or response
shape drift around empty condition lists.

