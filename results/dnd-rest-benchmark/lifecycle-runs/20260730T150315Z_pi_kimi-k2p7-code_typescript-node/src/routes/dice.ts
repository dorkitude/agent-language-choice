import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { parseDiceExpression } from '../rules.js';

export function handleDiceStats(res: ServerResponse, _params: unknown, body: unknown): void {
  const expr = (body as { expression?: unknown }).expression;
  const parsed = parseDiceExpression(expr);
  if (!parsed) {
    sendJSON(res, 400, { error: 'invalid expression' });
    return;
  }
  const { diceCount, sides, modifier } = parsed;
  const min = diceCount + modifier;
  const max = diceCount * sides + modifier;
  const average = (min + max) / 2;
  sendJSON(res, 200, {
    dice_count: diceCount,
    sides,
    modifier,
    min,
    max,
    average,
  });
}
