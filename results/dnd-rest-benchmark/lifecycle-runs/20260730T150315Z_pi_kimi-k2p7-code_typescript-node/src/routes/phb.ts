import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { isNonNegativeInteger, isPositiveInteger } from '../validators.js';

export function handleSpellSlots(res: ServerResponse, _params: unknown, body: unknown): void {
  const { class: className, level } = body as Record<string, unknown>;
  if (className !== 'wizard' || level !== 5) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  sendJSON(res, 200, {
    class: 'wizard',
    level: 5,
    slots: { '1': 4, '2': 3, '3': 2 },
  });
}

export function handleLongRest(res: ServerResponse, _params: unknown, body: unknown): void {
  const { level, hp_current, hp_max, hit_dice_spent, exhaustion_level } = body as Record<string, unknown>;
  if (
    !isPositiveInteger(level) ||
    !isNonNegativeInteger(hp_current) ||
    !isNonNegativeInteger(hp_max) ||
    !isNonNegativeInteger(hit_dice_spent) ||
    !isNonNegativeInteger(exhaustion_level)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const restored = Math.max(1, Math.floor(level / 2));
  sendJSON(res, 200, {
    hp_current: hp_max,
    hit_dice_spent: Math.max(0, hit_dice_spent - restored),
    exhaustion_level: Math.max(0, exhaustion_level - 1),
  });
}

export function handleEquipmentLoad(res: ServerResponse, _params: unknown, body: unknown): void {
  const { strength, weight } = body as Record<string, unknown>;
  if (!isPositiveInteger(strength) || !isNonNegativeInteger(weight)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const capacity = strength * 15;
  sendJSON(res, 200, {
    capacity,
    weight,
    encumbered: weight > capacity,
  });
}
