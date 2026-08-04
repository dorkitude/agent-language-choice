// Player's Handbook lookups and stateless resource math: spell slots, long
// rests, and encumbrance. No persistence.
import type { ServerResponse } from "node:http";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";

// Only wizard level 5 is modeled; any other class/level combination is
// reported as unsupported rather than approximated.
const WIZARD_LEVEL_5_SLOTS: Record<string, number> = { "1": 4, "2": 3, "3": 2 };

export function handleSpellSlots(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || typeof body.class !== "string" || !isValidInt(body.level, 1, 20)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (body.class !== "wizard" || body.level !== 5) {
    sendJson(res, 400, { error: "unsupported class or level" });
    return;
  }

  sendJson(res, 200, { class: body.class, level: body.level, slots: WIZARD_LEVEL_5_SLOTS });
}

export function handleLongRest(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    !isValidInt(body.level, 1, 20) ||
    !isValidInt(body.hp_current, 0, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.hp_max, 0, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.hit_dice_spent, 0, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.exhaustion_level, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const maxRecoverable = Math.max(1, Math.floor(body.level / 2));
  const hitDiceSpent = Math.max(0, body.hit_dice_spent - maxRecoverable);
  const exhaustionLevel = Math.max(0, body.exhaustion_level - 1);

  sendJson(res, 200, {
    hp_current: body.hp_max,
    hit_dice_spent: hitDiceSpent,
    exhaustion_level: exhaustionLevel,
  });
}

export function handleEquipmentLoad(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    !isValidInt(body.strength, 1, Number.MAX_SAFE_INTEGER) ||
    !isValidInt(body.weight, 0, Number.MAX_SAFE_INTEGER)
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const capacity = body.strength * 15;

  sendJson(res, 200, { capacity, weight: body.weight, encumbered: body.weight > capacity });
}
