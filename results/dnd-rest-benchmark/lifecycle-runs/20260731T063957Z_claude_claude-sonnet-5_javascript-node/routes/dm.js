import { sendJson, parseJsonBody } from '../lib/http.js';
import { campaigns, monsters, campaignEvents } from '../lib/stores.js';
import { CR_XP, LEVEL_THRESHOLDS, countMultiplier, difficultyForXp, DIFFICULTY_RECOMMENDATIONS } from '../lib/rules.js';

export function registerDmRoutes(router) {
  router.post('/v1/dm/encounter-builder', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const campaignId = body.data && body.data.campaign_id;
    const party = body.data && body.data.party;
    const monsterSlugs = body.data && body.data.monster_slugs;
    if (
      typeof campaignId !== 'string' ||
      campaignId.length === 0 ||
      !Array.isArray(party) ||
      !Array.isArray(monsterSlugs) ||
      monsterSlugs.length === 0 ||
      !monsterSlugs.every((slug) => typeof slug === 'string')
    ) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!campaigns.has(campaignId)) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }

    let baseXp = 0;
    for (const slug of monsterSlugs) {
      const record = monsters.get(slug);
      if (!record) {
        sendJson(res, 400, { error: 'unknown monster slug' });
        return;
      }
      const xp = CR_XP[String(record.cr)];
      if (xp === undefined) {
        sendJson(res, 400, { error: 'unsupported challenge rating' });
        return;
      }
      baseXp += xp;
    }
    const monsterCount = monsterSlugs.length;
    const multiplier = countMultiplier(monsterCount);
    const adjustedXp = baseXp * multiplier;

    const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
    for (const member of party) {
      const t = LEVEL_THRESHOLDS[member && member.level];
      if (!t) {
        sendJson(res, 400, { error: 'unsupported party level' });
        return;
      }
      thresholds.easy += t.easy;
      thresholds.medium += t.medium;
      thresholds.hard += t.hard;
      thresholds.deadly += t.deadly;
    }

    const difficulty = difficultyForXp(adjustedXp, thresholds);

    sendJson(res, 200, {
      campaign_id: campaignId,
      base_xp: baseXp,
      adjusted_xp: adjustedXp,
      difficulty,
      monster_count: monsterCount,
      recommendation: DIFFICULTY_RECOMMENDATIONS[difficulty],
    });
  });

  router.post('/v1/dm/loot-parcel', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const campaignId = body.data && body.data.campaign_id;
    const tier = body.data && body.data.tier;
    if (typeof campaignId !== 'string' || campaignId.length === 0 || !Number.isInteger(tier) || tier < 1) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!campaigns.has(campaignId)) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    sendJson(res, 200, {
      campaign_id: campaignId,
      coins_gp: 75 * tier,
      items: [{ slug: 'healing-potion', quantity: 2 * tier }],
    });
  });

  router.post('/v1/dm/session-recap', async (req, res) => {
    const body = await parseJsonBody(req, res);
    if (!body.ok) return;
    const campaignId = body.data && body.data.campaign_id;
    if (typeof campaignId !== 'string' || campaignId.length === 0) {
      sendJson(res, 400, { error: 'invalid request' });
      return;
    }
    if (!campaigns.has(campaignId)) {
      sendJson(res, 404, { error: 'campaign not found' });
      return;
    }
    const events = campaignEvents.listByCampaign(campaignId);
    const latest = events.length > 0 ? events[events.length - 1] : null;
    const summary = latest ? latest.summary : 'No sessions recorded yet.';
    const openThreads = latest ? ['Resolve goblin trail ambush'] : [];
    sendJson(res, 200, {
      campaign_id: campaignId,
      summary,
      open_threads: openThreads,
    });
  });
}
