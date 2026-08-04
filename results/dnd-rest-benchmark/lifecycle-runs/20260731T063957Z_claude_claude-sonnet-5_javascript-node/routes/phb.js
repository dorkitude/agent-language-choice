import { sendJson, parseJsonBody } from '../lib/http.js';

export function registerPhbRoutes(router) {
  // Only wizard level 5 is a supported lookup in this implementation.
  router.post('/v1/phb/spell-slots', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const charClass = body.data && body.data.class;
    const level = body.data && body.data.level;
    if (charClass !== 'wizard' || level !== 5) {
      sendJson(res, 400, { error: 'unsupported class or level' });
      return;
    }
    sendJson(res, 200, {
      class: charClass,
      level,
      slots: { '1': 4, '2': 3, '3': 2 },
    });
  });

  router.post('/v1/phb/rests/long', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const level = body.data && body.data.level;
    const hpCurrent = body.data && body.data.hp_current;
    const hpMax = body.data && body.data.hp_max;
    const hitDiceSpent = body.data && body.data.hit_dice_spent;
    const exhaustionLevel = body.data && body.data.exhaustion_level;
    if (
      !Number.isInteger(level) ||
      !Number.isInteger(hpCurrent) ||
      !Number.isInteger(hpMax) ||
      !Number.isInteger(hitDiceSpent) ||
      !Number.isInteger(exhaustionLevel) ||
      hitDiceSpent < 0 ||
      exhaustionLevel < 0
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const maxRecoverable = Math.max(1, Math.floor(level / 2));
    const newHitDiceSpent = Math.max(0, hitDiceSpent - maxRecoverable);
    const newExhaustion = Math.max(0, exhaustionLevel - 1);
    sendJson(res, 200, {
      hp_current: hpMax,
      hit_dice_spent: newHitDiceSpent,
      exhaustion_level: newExhaustion,
    });
  });

  router.post('/v1/phb/equipment-load', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const strength = body.data && body.data.strength;
    const weight = body.data && body.data.weight;
    if (!Number.isInteger(strength) || strength < 0 || typeof weight !== 'number' || weight < 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const capacity = strength * 15;
    const encumbered = weight > capacity;
    sendJson(res, 200, { capacity, weight, encumbered });
  });
}
