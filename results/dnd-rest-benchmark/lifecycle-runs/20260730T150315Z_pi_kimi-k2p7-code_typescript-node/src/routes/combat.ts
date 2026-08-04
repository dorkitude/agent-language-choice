import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  combatSessionExists,
  createCombatSession,
  getCombatSession,
  updateCombatSession,
} from '../repository.js';
import { sortCombatants } from '../rules.js';
import { isNonEmptyString, isPositiveInteger, isValidCombatant } from '../validators.js';
import type { CombatSession, Combatant } from '../types.js';

function combatSessionResponse(session: CombatSession) {
  const active = session.order[session.turn_index];
  return {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: { name: active.name, score: active.score },
    order: session.order.map(({ name, score }) => ({ name, score })),
  };
}

export function handleCreateCombatSession(res: ServerResponse, _params: unknown, body: unknown): void {
  const { id, combatants } = body as { id?: unknown; combatants?: Array<unknown> };
  if (!isNonEmptyString(id) || !Array.isArray(combatants) || combatants.length === 0) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const validated: Combatant[] = [];
  for (const c of combatants) {
    if (!isValidCombatant(c)) {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    validated.push(c);
  }

  if (combatSessionExists(id)) {
    sendJSON(res, 400, { error: 'session already exists' });
    return;
  }

  const session: CombatSession = {
    id,
    round: 1,
    turn_index: 0,
    order: sortCombatants(validated),
    conditions: {},
  };
  createCombatSession(session);
  sendJSON(res, 200, combatSessionResponse(session));
}

export function handleAddCondition(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  const session = getCombatSession(params.id);
  if (!session) {
    sendJSON(res, 404, { error: 'session not found' });
    return;
  }

  const { target, condition, duration_rounds } = body as {
    target?: unknown;
    condition?: unknown;
    duration_rounds?: unknown;
  };
  if (
    typeof target !== 'string' ||
    typeof condition !== 'string' ||
    !isPositiveInteger(duration_rounds)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const combatantExists = session.order.some((c) => c.name === target);
  if (!combatantExists) {
    sendJSON(res, 400, { error: 'invalid target' });
    return;
  }

  if (!session.conditions[target]) {
    session.conditions[target] = [];
  }
  session.conditions[target].push({ condition, remaining_rounds: duration_rounds });
  updateCombatSession(session);
  sendJSON(res, 200, {
    target,
    conditions: session.conditions[target],
  });
}

export function handleAdvanceCombat(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
): void {
  const session = getCombatSession(params.id);
  if (!session) {
    sendJSON(res, 404, { error: 'session not found' });
    return;
  }

  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }

  const active = session.order[session.turn_index];
  const activeConditions = session.conditions[active.name];
  if (activeConditions) {
    const updated = activeConditions
      .map((cond) => ({ condition: cond.condition, remaining_rounds: cond.remaining_rounds - 1 }))
      .filter((cond) => cond.remaining_rounds > 0);
    session.conditions[active.name] = updated;
  }

  updateCombatSession(session);
  sendJSON(res, 200, {
    ...combatSessionResponse(session),
    conditions: session.conditions,
  });
}
