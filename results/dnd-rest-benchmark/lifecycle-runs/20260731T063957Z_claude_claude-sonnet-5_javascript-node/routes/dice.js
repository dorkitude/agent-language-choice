import { sendJson, parseJsonBody } from '../lib/http.js';
import { parseDiceExpression } from '../lib/dice.js';

export function registerDiceRoutes(router) {
  router.post('/v1/dice/stats', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const parsed = parseDiceExpression(body.data && body.data.expression);
    if (!parsed) {
      sendJson(res, 400, { error: 'invalid expression' });
      return;
    }
    const { count, sides, modifier } = parsed;
    const min = count * 1 + modifier;
    const max = count * sides + modifier;
    const average = (count * (sides + 1)) / 2 + modifier;
    sendJson(res, 200, {
      dice_count: count,
      sides,
      modifier,
      min,
      max,
      average,
    });
  });

  router.post('/v1/checks/ability', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const { roll, modifier, dc } = body.data || {};
    if (typeof roll !== 'number' || typeof modifier !== 'number' || typeof dc !== 'number') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const total = roll + modifier;
    const success = total >= dc;
    const margin = total - dc;
    sendJson(res, 200, { total, success, margin });
  });
}
