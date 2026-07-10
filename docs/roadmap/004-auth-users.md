# 004 Username/Password Auth

Status: specified; evaluator suite added.

Spec: [`challenges/auth-users.md`](../../experiments/dnd-rest-benchmark/challenges/auth-users.md)  
Evaluator suite: `auth-users`

## Request

Add deterministic username/password registration and login APIs. This is not a
security benchmark; it tests whether agents can add simple user state without
breaking the growing service.

## Required Behaviors

- `POST /v1/auth/register`
- Reject duplicate usernames with HTTP 409
- Validate basic username/password inputs
- `POST /v1/auth/login`
- Return deterministic tokens of the form `session-<username>`
- Reject invalid credentials with HTTP 401

## Prompt Role

Maintenance agent.

## Scoring Notes

This stage adds cross-cutting concerns and intentional state collisions. It
should expose frameworks that hide request parsing or global application state
behind convention-heavy mechanisms.

