import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  addCombatCondition,
  combatSessionExists,
  createCombatSession,
  decrementConditions,
  getCombatSession,
  getConditions,
  getConditionsForTarget,
  updateCombatSessionRound,
} from '../db.js';
import { sortInitiative } from '../rules.js';
import type { Combatant } from '../types.js';

export function handleCreateCombatSession(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || typeof b.id !== 'string' || !Array.isArray(b.combatants) || b.combatants.length === 0) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (combatSessionExists(b.id)) {
    sendError(res, 400, 'session already exists');
    return true;
  }
  const combatants: Combatant[] = [];
  for (const c of b.combatants) {
    if (!c || typeof c.name !== 'string' || typeof c.dex !== 'number' || typeof c.roll !== 'number') {
      sendError(res, 400, 'invalid combatant');
      return true;
    }
    combatants.push({ name: c.name, dex: c.dex, roll: c.roll, score: c.roll + c.dex });
  }
  const order = sortInitiative(combatants);
  const session = {
    id: b.id,
    round: 1,
    turn_index: 0,
    combatants,
    order,
    conditions: {},
  };
  createCombatSession(session);
  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[session.turn_index],
    order: session.order,
  });
  return true;
}

export function handleAddCondition(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/combat\/sessions\/(.+)\/conditions$/);
  if (!match) return false;
  const sessionId = match[1];
  if (!combatSessionExists(sessionId)) {
    sendError(res, 404, 'session not found');
    return true;
  }
  const session = getCombatSession(sessionId)!;
  const b = body as any;
  if (!b || typeof b.target !== 'string' || typeof b.condition !== 'string' || !Number.isInteger(b.duration_rounds) || b.duration_rounds <= 0) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (!session.combatants.some((c) => c.name === b.target)) {
    sendError(res, 400, 'invalid target');
    return true;
  }
  addCombatCondition(sessionId, b.target, b.condition, b.duration_rounds);
  const list = getConditionsForTarget(sessionId, b.target);
  sendJson(res, 200, { target: b.target, conditions: list });
  return true;
}

export function handleAdvance(pathname: string, _body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/combat\/sessions\/(.+)\/advance$/);
  if (!match) return false;
  const sessionId = match[1];
  const session = getCombatSession(sessionId);
  if (!session) {
    sendError(res, 404, 'session not found');
    return true;
  }
  session.turn_index += 1;
  if (session.turn_index >= session.order.length) {
    session.turn_index = 0;
    session.round += 1;
  }
  updateCombatSessionRound(session.id, session.round, session.turn_index);
  const activeName = session.order[session.turn_index].name;
  decrementConditions(session.id, activeName);
  const conditionsResponse = getConditions(session.id, session.combatants.map((c) => c.name));
  sendJson(res, 200, {
    id: session.id,
    round: session.round,
    turn_index: session.turn_index,
    active: session.order[session.turn_index],
    conditions: conditionsResponse,
  });
  return true;
}
