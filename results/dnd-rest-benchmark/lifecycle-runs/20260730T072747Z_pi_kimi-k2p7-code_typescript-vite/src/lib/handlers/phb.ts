import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { isLevel } from '../validation.js';

export function handleSpellSlots(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || b.class !== 'wizard' || b.level !== 5) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  sendJson(res, 200, { class: 'wizard', level: 5, slots: { '1': 4, '2': 3, '3': 2 } });
  return true;
}

export function handleLongRest(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (
    !b ||
    !isLevel(b.level) ||
    typeof b.hp_current !== 'number' ||
    typeof b.hp_max !== 'number' ||
    typeof b.hit_dice_spent !== 'number' ||
    !Number.isInteger(b.hit_dice_spent) ||
    b.hit_dice_spent < 0 ||
    typeof b.exhaustion_level !== 'number' ||
    !Number.isInteger(b.exhaustion_level) ||
    b.exhaustion_level < 0
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const hpCurrent = b.hp_max;
  const recovered = Math.max(1, Math.floor(b.level / 2));
  const hitDiceSpent = Math.max(0, b.hit_dice_spent - recovered);
  const exhaustionLevel = Math.max(0, b.exhaustion_level - 1);
  sendJson(res, 200, { hp_current: hpCurrent, hit_dice_spent: hitDiceSpent, exhaustion_level: exhaustionLevel });
  return true;
}

export function handleEquipmentLoad(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (
    !b ||
    typeof b.strength !== 'number' ||
    !Number.isInteger(b.strength) ||
    b.strength < 1 ||
    b.strength > 30 ||
    typeof b.weight !== 'number' ||
    b.weight < 0
  ) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const capacity = b.strength * 15;
  sendJson(res, 200, { capacity, weight: b.weight, encumbered: b.weight > capacity });
  return true;
}
