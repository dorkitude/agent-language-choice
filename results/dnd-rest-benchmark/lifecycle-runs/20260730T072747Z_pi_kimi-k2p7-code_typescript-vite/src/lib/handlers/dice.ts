import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { diceStats, parseDiceExpression, sortInitiative } from '../rules.js';

export function handleDiceStats(body: unknown, res: ServerResponse): boolean {
  const dice = parseDiceExpression((body as any)?.expression);
  if (!dice) {
    sendError(res, 400, 'invalid expression');
    return true;
  }
  sendJson(res, 200, diceStats(dice));
  return true;
}

export function handleAbilityCheck(body: unknown, res: ServerResponse): boolean {
  const { roll, modifier, dc } = body as any;
  if (typeof roll !== 'number' || typeof modifier !== 'number' || typeof dc !== 'number') {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const total = roll + modifier;
  sendJson(res, 200, { total, success: total >= dc, margin: total - dc });
  return true;
}

export function handleInitiativeOrder(body: unknown, res: ServerResponse): boolean {
  const combatants = (body as any)?.combatants;
  if (!Array.isArray(combatants)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const order = sortInitiative(
    combatants.filter(
      (c: any) => c && typeof c.name === 'string' && typeof c.dex === 'number' && typeof c.roll === 'number',
    ),
  );
  sendJson(res, 200, { order });
  return true;
}
