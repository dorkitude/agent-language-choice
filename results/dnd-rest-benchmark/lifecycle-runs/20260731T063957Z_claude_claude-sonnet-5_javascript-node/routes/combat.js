import { sendJson, parseJsonBody } from '../lib/http.js';
import { combatSessions } from '../lib/stores.js';
import { computeOrder, activeSummary, conditionsSummary } from '../lib/combat.js';

export function registerCombatRoutes(router) {
  router.post('/v1/combat/sessions', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const id = body.data && body.data.id;
    const combatants = body.data && body.data.combatants;
    if (typeof id !== 'string' || id.length === 0 || !Array.isArray(combatants) || combatants.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (combatSessions.has(id)) {
      sendJson(res, 400, { error: 'session already exists' });
      return;
    }
    for (const c of combatants) {
      if (typeof c.name !== 'string' || typeof c.dex !== 'number' || typeof c.roll !== 'number') {
        sendJson(res, 400, { error: 'invalid combatant' });
        return;
      }
    }
    const order = computeOrder(combatants);
    const session = { id, round: 1, turn_index: 0, order };
    combatSessions.set(id, session);
    sendJson(res, 200, {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: activeSummary(session),
      order: order.map((c) => ({ name: c.name, score: c.score })),
    });
  });

  // Matches only the two supported sub-actions; anything else falls through
  // to the router's 404, same as the original literal-alternation regex.
  router.post(
    /^\/v1\/combat\/sessions\/([^/]+)\/(conditions|advance)$/,
    async (req, res, { sessionId, action }) => {
      const session = combatSessions.get(sessionId);
      if (!session) {
        sendJson(res, 404, { error: 'session not found' });
        return;
      }

      if (action === 'conditions') {
        const body = await parseJsonBody(req, res);
        if (!body.ok) return;
        const target = body.data && body.data.target;
        const condition = body.data && body.data.condition;
        const durationRounds = body.data && body.data.duration_rounds;
        if (
          typeof target !== 'string' ||
          typeof condition !== 'string' ||
          !Number.isInteger(durationRounds) ||
          durationRounds <= 0
        ) {
          sendJson(res, 400, { error: 'invalid request' });
          return;
        }
        const combatant = session.order.find((c) => c.name === target);
        if (!combatant) {
          sendJson(res, 400, { error: 'unknown target' });
          return;
        }
        combatant.conditions.push({ condition, remaining_rounds: durationRounds });
        combatSessions.set(sessionId, session);
        sendJson(res, 200, {
          target: combatant.name,
          conditions: combatant.conditions.map((c) => ({
            condition: c.condition,
            remaining_rounds: c.remaining_rounds,
          })),
        });
        return;
      }

      // action === 'advance'
      session.turn_index += 1;
      if (session.turn_index >= session.order.length) {
        session.turn_index = 0;
        session.round += 1;
      }
      const active = session.order[session.turn_index];
      active.conditions = active.conditions
        .map((c) => ({ ...c, remaining_rounds: c.remaining_rounds - 1 }))
        .filter((c) => c.remaining_rounds > 0);
      const conditions = conditionsSummary(session);
      conditions[active.name] = active.conditions.map((c) => ({
        condition: c.condition,
        remaining_rounds: c.remaining_rounds,
      }));
      combatSessions.set(sessionId, session);
      sendJson(res, 200, {
        id: session.id,
        round: session.round,
        turn_index: session.turn_index,
        active: activeSummary(session),
        conditions,
      });
    },
    ['sessionId', 'action']
  );
}
