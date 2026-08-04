import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { campaignExists, getEventsByCampaign, getMonster } from '../db.js';
import { difficultyLabel, multiplier, recommendationFor } from '../rules.js';
import { XP_TABLE } from '../constants.js';
import { isNonEmptyString } from '../validation.js';

export function handleEncounterBuilder(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || !isNonEmptyString(b.campaign_id) || !Array.isArray(b.party) || !Array.isArray(b.monster_slugs)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (!campaignExists(b.campaign_id)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const monsterCounts: Record<string, number> = {};
  for (const slug of b.monster_slugs) {
    if (typeof slug !== 'string' || slug.length === 0) {
      sendError(res, 400, 'invalid monster slug');
      return true;
    }
    monsterCounts[slug] = (monsterCounts[slug] || 0) + 1;
  }
  let baseXp = 0;
  let monsterCount = 0;
  for (const [slug, count] of Object.entries(monsterCounts)) {
    const monster = getMonster(slug);
    if (!monster) {
      sendError(res, 404, 'monster not found');
      return true;
    }
    if (!(monster.cr in XP_TABLE)) {
      sendError(res, 400, 'unsupported monster cr');
      return true;
    }
    baseXp += XP_TABLE[monster.cr] * count;
    monsterCount += count;
  }
  const adjusted = baseXp * multiplier(monsterCount);
  for (const p of b.party) {
    if (!p || typeof p.level !== 'number') {
      sendError(res, 400, 'invalid party member');
      return true;
    }
  }
  const difficulty = difficultyLabel(adjusted, b.party.length);
  sendJson(res, 200, {
    campaign_id: b.campaign_id,
    base_xp: baseXp,
    adjusted_xp: adjusted,
    difficulty,
    monster_count: monsterCount,
    recommendation: recommendationFor(difficulty),
  });
  return true;
}

export function handleLootParcel(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || !isNonEmptyString(b.campaign_id) || typeof b.tier !== 'number' || b.tier !== 1) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (!campaignExists(b.campaign_id)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  sendJson(res, 200, {
    campaign_id: b.campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }],
  });
  return true;
}

export function handleSessionRecap(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || !isNonEmptyString(b.campaign_id)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (!campaignExists(b.campaign_id)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const events = getEventsByCampaign(b.campaign_id);
  const latestEvent = events[events.length - 1];
  let summary = 'Nothing to recap.';
  const openThreads: string[] = [];
  if (latestEvent) {
    summary = latestEvent.summary;
    const trimmed = summary.replace(/\.$/, '');
    const idx = trimmed.lastIndexOf(' the ');
    if (idx >= 0) {
      const topic = trimmed.substring(idx + ' the '.length);
      openThreads.push(`Resolve ${topic} ambush`);
    } else {
      openThreads.push(`Resolve ${trimmed}`);
    }
  }
  sendJson(res, 200, {
    campaign_id: b.campaign_id,
    summary,
    open_threads: openThreads,
  });
  return true;
}
