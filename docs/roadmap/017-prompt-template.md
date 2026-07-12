# 017 Agent Prompt Template

The lifecycle harness builds prompts from
[`rest_harness.py`](../../experiments/dnd-rest-benchmark/rest_harness.py). Each
matrix cell receives the same structure with target-specific language/framework
guidance and stage-specific challenge text.

## Creative Role

```text
Create the first implementation from the seeded starter files.
```

## Maintenance Role

```text
You are a fresh maintenance agent inheriting this existing codebase. Add the
requested feature stage while preserving all existing API behavior.
```

## Bug-Fix Role

```text
You are a fresh bug-fix agent inheriting this existing codebase after a
deterministic evaluator failure.
```

## Prompt Body

```text
You are participating in a staged programming-language benchmark.

Target: {target.id}
Language: {target.language}
Framework/runtime: {target.framework}
Lifecycle stage: {stage.id}
Shot kind: {shot_kind}

{role}

Use the exact latest runtime/framework versions already pinned in this
workspace. Do not downgrade packages or replace the requested framework.

Relevant version pins:
{versions}

Target guidance:
{target.guidance}

Contract:
- Work only in the current directory.
- Keep or create ./run.sh.
- ./run.sh must start the HTTP server in the foreground.
- The server must listen on 127.0.0.1 using the PORT environment variable.
- Do not start the server before finishing your answer.
- Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
- Prefer deterministic, minimal code.

Stage spec:

{stage.spec_path contents}

{failure report, only for bug-fix shots}

Finish when ./run.sh is ready.
```

## Failure Report

Bug-fix agents receive deterministic setup/server/evaluator output. The report
includes failing test IDs, recent stdout/stderr, and the evaluator's JSON
summary when available. The report is intentionally mechanical so that retries
measure whether the model can repair against concrete feedback.
