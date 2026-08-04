import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { sortCombatants } from '../rules.js';
import { isValidCombatant } from '../validators.js';
import type { Combatant } from '../types.js';

export function handleInitiativeOrder(res: ServerResponse, _params: unknown, body: unknown): void {
  const { combatants } = body as { combatants?: Array<unknown> };
  if (!Array.isArray(combatants)) {
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

  const order = sortCombatants(validated).map(({ name, score }) => ({ name, score }));
  sendJSON(res, 200, { order });
}
