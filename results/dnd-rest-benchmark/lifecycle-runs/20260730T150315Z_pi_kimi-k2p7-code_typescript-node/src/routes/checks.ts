import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';

export function handleAbilityCheck(res: ServerResponse, _params: unknown, body: unknown): void {
  const { roll, modifier, dc } = body as { roll?: unknown; modifier?: unknown; dc?: unknown };
  if (
    typeof roll !== 'number' ||
    typeof modifier !== 'number' ||
    typeof dc !== 'number' ||
    !Number.isFinite(roll) ||
    !Number.isFinite(modifier) ||
    !Number.isFinite(dc)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const total = roll + modifier;
  const success = total >= dc;
  const margin = total - dc;
  sendJSON(res, 200, { total, success, margin });
}
