/** Dice math and ability check resolution — pure functions, no persistence. */

import type { ApiResult, JsonValue } from '../types.ts';

export function diceStats(body: JsonValue): ApiResult {
  const expression = body.expression;
  if (typeof expression !== 'string') {
    return { status: 400, body: { error: 'expression must be a string' } };
  }
  const match = /^(\d+)d(\d+)(?:([+-])(\d+))?$/.exec(expression.trim());
  if (!match) {
    return { status: 400, body: { error: 'invalid expression' } };
  }
  const diceCount = parseInt(match[1], 10);
  const sides = parseInt(match[2], 10);
  const sign = match[3];
  const modAmount = match[4] !== undefined ? parseInt(match[4], 10) : 0;
  const modifier = sign === '-' ? -modAmount : modAmount;

  if (diceCount <= 0 || sides <= 0) {
    return { status: 400, body: { error: 'count and sides must be positive' } };
  }

  const min = diceCount * 1 + modifier;
  const max = diceCount * sides + modifier;
  const average = (diceCount * (1 + sides)) / 2 + modifier;

  return {
    status: 200,
    body: {
      dice_count: diceCount,
      sides,
      modifier,
      min,
      max,
      average,
    },
  };
}

export function abilityCheck(body: JsonValue): ApiResult {
  const roll = body.roll;
  const modifier = body.modifier;
  const dc = body.dc;
  if (typeof roll !== 'number' || typeof modifier !== 'number' || typeof dc !== 'number') {
    return { status: 400, body: { error: 'roll, modifier, dc must be numbers' } };
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  return { status: 200, body: { total, success, margin } };
}
