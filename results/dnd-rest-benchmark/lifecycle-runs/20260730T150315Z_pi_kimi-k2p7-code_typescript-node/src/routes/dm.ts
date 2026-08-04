import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  campaignExists,
  getCampaignCharacters,
  getCampaignEvents,
  getMonster,
  listMonsterSlugs,
} from '../repository.js';
import {
  CR_XP,
  ENCOUNTER_THRESHOLDS,
  difficultyFromAdjustedXP,
  multiplierForMonsterCount,
  recommendationForDifficulty,
  resolveTrailThread,
} from '../rules.js';
import { isNonEmptyString } from '../validators.js';

export function handleEncounterBuilder(res: ServerResponse, _params: unknown, body: unknown): void {
  const { campaign_id, party, monster_slugs } = body as {
    campaign_id?: unknown;
    party?: unknown;
    monster_slugs?: unknown;
  };
  if (
    !isNonEmptyString(campaign_id) ||
    !Array.isArray(party) ||
    party.length === 0 ||
    !Array.isArray(monster_slugs) ||
    monster_slugs.length === 0
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (!campaignExists(campaign_id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const levels: number[] = [];
  for (const p of party) {
    if (typeof p !== 'object' || p == null || typeof (p as { level?: unknown }).level !== 'number') {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    const level = Number((p as { level: number }).level);
    if (!Number.isInteger(level) || level < 1 || level > 20 || !ENCOUNTER_THRESHOLDS[level]) {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    levels.push(level);
  }

  const counts: Record<string, number> = {};
  for (const slug of monster_slugs) {
    if (typeof slug !== 'string') {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    counts[slug] = (counts[slug] || 0) + 1;
  }

  let baseXP = 0;
  const monsterCount = monster_slugs.length;
  for (const [slug, count] of Object.entries(counts)) {
    const monster = getMonster(slug);
    if (!monster) {
      sendJSON(res, 400, { error: 'monster not found' });
      return;
    }
    const xp = CR_XP[monster.cr];
    if (xp === undefined) {
      sendJSON(res, 400, { error: 'unsupported cr' });
      return;
    }
    baseXP += xp * count;
  }

  const multiplier = multiplierForMonsterCount(monsterCount);
  const adjustedXP = baseXP * multiplier;
  const thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 };
  for (const level of levels) {
    const t = ENCOUNTER_THRESHOLDS[level];
    thresholds.easy += t.easy;
    thresholds.medium += t.medium;
    thresholds.hard += t.hard;
    thresholds.deadly += t.deadly;
  }

  const difficulty = difficultyFromAdjustedXP(adjustedXP, thresholds);
  const recommendation = recommendationForDifficulty(difficulty);
  sendJSON(res, 200, {
    campaign_id,
    base_xp: baseXP,
    adjusted_xp: adjustedXP,
    difficulty,
    monster_count: monsterCount,
    recommendation,
  });
}

export function handleLootParcel(res: ServerResponse, _params: unknown, body: unknown): void {
  const { campaign_id, tier, seed } = body as {
    campaign_id?: unknown;
    tier?: unknown;
    seed?: unknown;
  };
  if (!isNonEmptyString(campaign_id) || typeof tier !== 'number' || !Number.isInteger(tier) || tier !== 1) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (seed !== undefined && (typeof seed !== 'number' || !Number.isInteger(seed))) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (!campaignExists(campaign_id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  sendJSON(res, 200, {
    campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }],
  });
}

export function handleSessionRecap(res: ServerResponse, _params: unknown, body: unknown): void {
  const { campaign_id } = body as { campaign_id?: unknown };
  if (!isNonEmptyString(campaign_id)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (!campaignExists(campaign_id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const events = getCampaignEvents(campaign_id);
  const summarizedEvents = events.filter((e) => typeof e.summary === 'string' && e.summary.length > 0);
  const characters = getCampaignCharacters(campaign_id);
  const firstMonster = listMonsterSlugs()[0] ?? 'monster';
  const actor = characters[0]?.name ?? 'The party';

  let summary: string;
  let open_threads: string[];
  if (summarizedEvents.length > 0) {
    summary = summarizedEvents[summarizedEvents.length - 1].summary as string;
    const threadEvents = summarizedEvents.filter((e) => e.kind === 'thread');
    open_threads =
      threadEvents.length > 0
        ? threadEvents.map((e) => e.summary as string)
        : [resolveTrailThread(summary, firstMonster)];
  } else {
    summary = `${actor} scouts the ${firstMonster} trail.`;
    open_threads = [resolveTrailThread(summary, firstMonster)];
  }

  sendJSON(res, 200, { campaign_id, summary, open_threads });
}
