# 001 Core D&D Engine API

Status: completed in the first lifecycle matrix.

Spec: [`challenges/core.md`](../../experiments/dnd-rest-benchmark/challenges/core.md)  
Evaluator suite: `core`

## Request

Build the initial D&D REST API from seeded starter files. The implementation
must expose a foreground `./run.sh`, listen on `127.0.0.1:$PORT`, speak
HTTP/JSON, and avoid runtime network access.

## Required Behaviors

- `GET /health`
- Dice expression statistics for deterministic expressions such as `2d6+3`
- Ability-check totals, success flags, and margins
- Encounter adjusted XP and difficulty classification
- Initiative ordering with deterministic tie-breakers

## Prompt Role

Creative agent:

```text
Create the first implementation from the seeded starter files.
```

The full prompt template is in [010-prompt-template.md](010-prompt-template.md).

## Scoring Notes

This stage tests whether a model can produce a small, clean HTTP/JSON service
in the target language/framework with minimal scaffolding. It favors languages
with simple server startup, obvious JSON handling, and deterministic compiler or
runtime feedback.

