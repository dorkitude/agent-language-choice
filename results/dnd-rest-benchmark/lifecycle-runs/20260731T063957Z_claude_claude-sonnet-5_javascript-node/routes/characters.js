import { sendJson, parseJsonBody } from '../lib/http.js';
import { proficiencyBonus } from '../lib/rules.js';

const ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

export function registerCharacterRoutes(router) {
  router.post('/v1/characters/ability-modifier', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const score = body.data && body.data.score;
    if (!Number.isInteger(score) || score < 1 || score > 30) {
      sendJson(res, 400, { error: 'invalid score' });
      return;
    }
    const modifier = Math.floor((score - 10) / 2);
    sendJson(res, 200, { score, modifier });
  });

  router.post('/v1/characters/proficiency', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const level = body.data && body.data.level;
    const bonus = proficiencyBonus(level);
    if (bonus === null) {
      sendJson(res, 400, { error: 'invalid level' });
      return;
    }
    sendJson(res, 200, { level, proficiency_bonus: bonus });
  });

  router.post('/v1/characters/derived-stats', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const level = body.data && body.data.level;
    const abilities = body.data && body.data.abilities;
    const armor = body.data && body.data.armor;
    const bonus = proficiencyBonus(level);
    if (bonus === null || !abilities || typeof abilities !== 'object' || !armor || typeof armor !== 'object') {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    const modifiers = {};
    for (const key of ABILITY_KEYS) {
      const score = abilities[key];
      if (!Number.isInteger(score) || score < 1 || score > 30) {
        sendJson(res, 400, { error: 'invalid ability score' });
        return;
      }
      modifiers[key] = Math.floor((score - 10) / 2);
    }
    if (typeof armor.base !== 'number' || typeof armor.dex_cap !== 'number') {
      sendJson(res, 400, { error: 'invalid armor' });
      return;
    }
    const shieldBonus = armor.shield === true ? 2 : 0;
    const hpMax = level * (6 + modifiers.con);
    const armorClass = armor.base + Math.min(modifiers.dex, armor.dex_cap) + shieldBonus;
    sendJson(res, 200, {
      level,
      proficiency_bonus: bonus,
      hp_max: hpMax,
      armor_class: armorClass,
      modifiers,
    });
  });
}
