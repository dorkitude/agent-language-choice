/**
 * Campaign-scoped factions and bounded per-character reputation history.
 * Reputation totals are clamped to [-100,100]; each accepted change appends
 * an immutable history record so the DM (and the affected player) can audit
 * how a total was reached.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  findMemberByCharacterId,
  requireParticipant,
} from './shared.ts';

type FactionRow = {
  campaign_id: string;
  faction_id: string;
  name: string;
};

type ReputationHistoryRow = {
  faction_id: string;
  character_id: string;
  reputation: number;
  delta: number;
  reason: string;
};

const FACTION_NOT_FOUND: ApiResult = { status: 404, body: { error: 'faction not found' } };
const REPUTATION_MIN = -100;
const REPUTATION_MAX = 100;

function findFaction(db: ReturnType<typeof getDb>, campaignId: string, factionId: string): FactionRow | ApiResult {
  const faction = db
    .prepare('SELECT campaign_id, faction_id, name FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?')
    .get(campaignId, factionId) as FactionRow | undefined;
  return faction ?? FACTION_NOT_FOUND;
}

function nextReputationSequence(db: ReturnType<typeof getDb>, campaignId: string, factionId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?',
    )
    .get(campaignId, factionId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createCampaignFaction(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create factions' } };
  }

  const factionId = body.faction_id;
  if (typeof factionId !== 'string' || factionId.length === 0) {
    return { status: 400, body: { error: 'faction_id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const existing = findFaction(db, campaignId, factionId);
  if (!isApiResult(existing)) {
    return { status: 409, body: { error: 'faction_id already exists in this campaign' } };
  }

  db.prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)').run(
    campaignId,
    factionId,
    name,
  );

  return { status: 201, body: { faction_id: factionId, name } };
}

export function adjustFactionReputation(
  authHeader: string | undefined,
  campaignId: string,
  factionId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may change reputation' } };
  }

  const faction = findFaction(db, campaignId, factionId);
  if (isApiResult(faction)) return faction;

  const characterId = body.character_id;
  if (typeof characterId !== 'string' || characterId.length === 0) {
    return { status: 400, body: { error: 'character_id must be a non-empty string' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) {
    return { status: 400, body: { error: 'character_id must identify a campaign member character' } };
  }

  const delta = body.delta;
  if (typeof delta !== 'number' || !Number.isInteger(delta) || delta === 0 || delta < -25 || delta > 25) {
    return { status: 400, body: { error: 'delta must be a nonzero integer in [-25,25]' } };
  }

  const reason = body.reason;
  if (typeof reason !== 'string' || reason.length === 0) {
    return { status: 400, body: { error: 'reason must be a non-empty string' } };
  }

  const current = db
    .prepare(
      'SELECT reputation FROM play_campaign_faction_reputation WHERE campaign_id = ? AND faction_id = ? AND character_id = ?',
    )
    .get(campaignId, factionId, characterId) as { reputation: number } | undefined;

  const currentTotal = current?.reputation ?? 0;
  const nextTotal = Math.max(REPUTATION_MIN, Math.min(REPUTATION_MAX, currentTotal + delta));

  db.prepare(
    `INSERT INTO play_campaign_faction_reputation (campaign_id, faction_id, character_id, reputation)
     VALUES (?, ?, ?, ?)
     ON CONFLICT (campaign_id, faction_id, character_id) DO UPDATE SET reputation = excluded.reputation`,
  ).run(campaignId, factionId, characterId, nextTotal);

  const sequence = nextReputationSequence(db, campaignId, factionId);
  db.prepare(
    `INSERT INTO play_campaign_faction_reputation_history
       (campaign_id, faction_id, sequence, character_id, reputation, delta, reason)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, factionId, sequence, characterId, nextTotal, delta, reason);

  return {
    status: 201,
    body: { faction_id: factionId, character_id: characterId, reputation: nextTotal, delta, reason },
  };
}

export function getFactionReputation(authHeader: string | undefined, campaignId: string, factionId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const faction = findFaction(db, campaignId, factionId);
  if (isApiResult(faction)) return faction;

  const rows = db
    .prepare(
      `SELECT faction_id, character_id, reputation, delta, reason
       FROM play_campaign_faction_reputation_history
       WHERE campaign_id = ? AND faction_id = ?
       ORDER BY sequence ASC`,
    )
    .all(campaignId, factionId) as ReputationHistoryRow[];

  let entries = rows;
  if (actor.username !== campaign.owner) {
    const ownCharacterId = db
      .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
      .get(campaignId, actor.username) as { character_id: string } | undefined;
    entries = ownCharacterId ? rows.filter((row) => row.character_id === ownCharacterId.character_id) : [];
  }

  return {
    status: 200,
    body: {
      faction_id: factionId,
      entries: entries.map((entry) => ({
        faction_id: entry.faction_id,
        character_id: entry.character_id,
        reputation: entry.reputation,
        delta: entry.delta,
        reason: entry.reason,
      })),
    },
  };
}
