/** Player's Handbook rules: spell slots, long rests, and carrying capacity. */

import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';

// Only wizard level 5 is supported; other class/level combinations are rejected explicitly.
const WIZARD_SPELL_SLOTS: Record<number, Record<string, number>> = {
  5: { '1': 4, '2': 3, '3': 2 },
};

export function spellSlots(body: JsonValue): ApiResult {
  const klass = body.class;
  if (typeof klass !== 'string' || klass.length === 0) {
    return { status: 400, body: { error: 'class must be a non-empty string' } };
  }

  const level = body.level;
  if (!isValidIntInRange(level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }

  if (klass !== 'wizard' || !(level in WIZARD_SPELL_SLOTS)) {
    return { status: 400, body: { error: 'unsupported class/level combination' } };
  }

  return { status: 200, body: { class: klass, level, slots: WIZARD_SPELL_SLOTS[level] } };
}

export function longRest(body: JsonValue): ApiResult {
  const level = body.level;
  if (!isValidIntInRange(level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }

  const hpMax = body.hp_max;
  if (!isValidIntInRange(hpMax, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'hp_max must be a non-negative integer' } };
  }

  const hpCurrent = body.hp_current;
  if (!isValidIntInRange(hpCurrent, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'hp_current must be a non-negative integer' } };
  }

  const hitDiceSpent = body.hit_dice_spent;
  if (!isValidIntInRange(hitDiceSpent, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'hit_dice_spent must be a non-negative integer' } };
  }

  const exhaustionLevel = body.exhaustion_level;
  if (!isValidIntInRange(exhaustionLevel, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'exhaustion_level must be a non-negative integer' } };
  }

  const maxRecoverable = Math.max(1, Math.floor(level / 2));
  const recovered = Math.min(hitDiceSpent, maxRecoverable);

  return {
    status: 200,
    body: {
      hp_current: hpMax,
      hit_dice_spent: hitDiceSpent - recovered,
      exhaustion_level: Math.max(0, exhaustionLevel - 1),
    },
  };
}

export function equipmentLoad(body: JsonValue): ApiResult {
  const strength = body.strength;
  if (!isValidIntInRange(strength, 1, 30)) {
    return { status: 400, body: { error: 'strength must be an integer from 1 through 30' } };
  }

  const weight = body.weight;
  if (typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0) {
    return { status: 400, body: { error: 'weight must be a non-negative number' } };
  }

  const capacity = strength * 15;
  return {
    status: 200,
    body: { capacity, weight, encumbered: weight > capacity },
  };
}
