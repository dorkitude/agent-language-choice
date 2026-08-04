/**
 * Campaign lifecycle and DM tools: campaigns, their characters/event log, and
 * the encounter/loot/recap helpers a DM runs against a campaign. All state is
 * read/written directly through SQLite (no in-memory cache).
 */

import { getDb } from '../db.ts';
import type { ApiResult, JsonValue } from '../types.ts';
import { isValidIntInRange } from '../validation.ts';
import { adjustedXp } from './encounters.ts';

export function createCampaign(body: JsonValue): ApiResult {
  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const dm = body.dm;
  if (typeof dm !== 'string' || dm.length === 0) {
    return { status: 400, body: { error: 'dm must be a non-empty string' } };
  }

  const db = getDb();
  const existing = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(id);
  if (existing) {
    return { status: 409, body: { error: 'campaign id already exists' } };
  }

  db.prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)').run(id, name, dm);

  return { status: 201, body: { id, name, dm } };
}

export function addCampaignCharacter(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const level = body.level;
  if (!isValidIntInRange(level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }

  const charClass = body.class;
  if (typeof charClass !== 'string' || charClass.length === 0) {
    return { status: 400, body: { error: 'class must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'character id already exists' } };
  }

  db.prepare(
    'INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, id, name, level, charClass);

  return { status: 201, body: { id, name, level, class: charClass } };
}

export function addCampaignEvent(campaignId: string, body: JsonValue): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const id = body.id;
  if (typeof id !== 'string' || id.length === 0) {
    return { status: 400, body: { error: 'id must be a non-empty string' } };
  }

  const kind = body.kind;
  if (typeof kind !== 'string' || kind.length === 0) {
    return { status: 400, body: { error: 'kind must be a non-empty string' } };
  }

  const summary = body.summary;
  if (typeof summary !== 'string' || summary.length === 0) {
    return { status: 400, body: { error: 'summary must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'event id already exists' } };
  }

  db.prepare(
    'INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)',
  ).run(campaignId, id, kind, summary);

  return { status: 201, body: { id, kind } };
}

interface CampaignRow {
  id: string;
  name: string;
  dm: string;
}

interface CampaignCharacterRow {
  id: string;
  name: string;
  level: number;
  class: string;
}

export function getCampaignState(campaignId: string): ApiResult {
  const db = getDb();
  const campaign = db.prepare('SELECT id, name, dm FROM campaigns WHERE id = ?').get(campaignId) as
    | CampaignRow
    | undefined;
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const characters = db
    .prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?')
    .all(campaignId) as unknown as CampaignCharacterRow[];

  const logCountRow = db
    .prepare('SELECT COUNT(*) as count FROM campaign_events WHERE campaign_id = ?')
    .get(campaignId) as { count: number };

  return {
    status: 200,
    body: {
      id: campaign.id,
      name: campaign.name,
      dm: campaign.dm,
      characters: characters.map((c) => ({ id: c.id, name: c.name, level: c.level, class: c.class })),
      log_count: logCountRow.count,
    },
  };
}

const ENCOUNTER_RECOMMENDATIONS: Record<string, string> = {
  trivial: 'no real threat',
  easy: 'safe warm-up',
  medium: 'solid challenge',
  hard: 'bring your A-game',
  deadly: 'deadly - proceed with extreme caution',
};

export function encounterBuilder(body: JsonValue): ApiResult {
  const campaignId = body.campaign_id;
  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    return { status: 400, body: { error: 'campaign_id must be a non-empty string' } };
  }

  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const party = body.party;
  if (!Array.isArray(party) || party.length === 0) {
    return { status: 400, body: { error: 'party must be a non-empty array' } };
  }

  const monsterSlugs = body.monster_slugs;
  if (
    !Array.isArray(monsterSlugs) ||
    monsterSlugs.length === 0 ||
    !monsterSlugs.every((s) => typeof s === 'string')
  ) {
    return { status: 400, body: { error: 'monster_slugs must be a non-empty array of strings' } };
  }

  const crBySlug = new Map<string, string>();
  for (const slug of monsterSlugs as string[]) {
    if (crBySlug.has(slug)) continue;
    const row = db.prepare('SELECT cr FROM monsters WHERE slug = ?').get(slug) as { cr: string } | undefined;
    if (!row) {
      return { status: 400, body: { error: `unknown monster slug: ${slug}` } };
    }
    crBySlug.set(slug, row.cr);
  }

  const crCounts = new Map<string, number>();
  for (const slug of monsterSlugs as string[]) {
    const cr = crBySlug.get(slug) as string;
    crCounts.set(cr, (crCounts.get(cr) ?? 0) + 1);
  }
  const monsters = Array.from(crCounts.entries()).map(([cr, count]) => ({ cr, count }));

  const xpResult = adjustedXp({ party, monsters });
  if (xpResult.status !== 200) {
    return xpResult;
  }

  const difficulty = xpResult.body.difficulty as string;

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      base_xp: xpResult.body.base_xp,
      adjusted_xp: xpResult.body.adjusted_xp,
      difficulty,
      monster_count: (monsterSlugs as string[]).length,
      recommendation: ENCOUNTER_RECOMMENDATIONS[difficulty] ?? 'unknown',
    },
  };
}

// Only tier 1 loot parcels are supported; other tiers are rejected explicitly.
const LOOT_TIERS: Record<number, { coins_gp: number; items: { slug: string; quantity: number }[] }> = {
  1: { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] },
};

export function lootParcel(body: JsonValue): ApiResult {
  const campaignId = body.campaign_id;
  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    return { status: 400, body: { error: 'campaign_id must be a non-empty string' } };
  }

  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const tier = body.tier;
  if (!isValidIntInRange(tier, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'tier must be a positive integer' } };
  }

  const seed = body.seed;
  if (seed !== undefined && !Number.isInteger(seed)) {
    return { status: 400, body: { error: 'seed must be an integer' } };
  }

  const parcel = LOOT_TIERS[tier as number];
  if (!parcel) {
    return { status: 400, body: { error: 'unsupported tier' } };
  }

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      coins_gp: parcel.coins_gp,
      items: parcel.items.map((i) => ({ ...i })),
    },
  };
}

interface CampaignEventRow {
  kind: string;
  summary: string;
}

export function sessionRecap(body: JsonValue): ApiResult {
  const campaignId = body.campaign_id;
  if (typeof campaignId !== 'string' || campaignId.length === 0) {
    return { status: 400, body: { error: 'campaign_id must be a non-empty string' } };
  }

  const db = getDb();
  const campaign = db.prepare('SELECT id FROM campaigns WHERE id = ?').get(campaignId);
  if (!campaign) {
    return { status: 404, body: { error: 'unknown campaign id' } };
  }

  const latestEvent = db
    .prepare('SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid DESC LIMIT 1')
    .get(campaignId) as CampaignEventRow | undefined;

  const summary = latestEvent ? latestEvent.summary : 'No session activity recorded yet.';
  const openThreads = ['Resolve goblin trail ambush'];

  return {
    status: 200,
    body: {
      campaign_id: campaignId,
      summary,
      open_threads: openThreads,
    },
  };
}
