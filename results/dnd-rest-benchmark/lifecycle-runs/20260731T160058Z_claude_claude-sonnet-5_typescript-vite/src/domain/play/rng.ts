/**
 * Campaign-scoped deterministic RNG seed and immutable roll ledger. Rolls are
 * derived purely from the configured seed, the append-order sequence, the
 * roll_id, and the number of sides -- never from wall-clock time, process
 * RNG state, or any other non-deterministic source.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

const MODULUS = 4294967296; // 2^32

function computeRollResult(seed: string, sequence: number, rollId: string, sides: number): number {
  const byteString = `${seed}|${sequence}|${rollId}|${sides}`;
  const bytes = new TextEncoder().encode(byteString);
  let acc = 0;
  for (const b of bytes) {
    acc = (acc * 31 + b) % MODULUS;
  }
  return (acc % sides) + 1;
}

interface RollRow {
  roll_id: string;
  sides: number;
  result: number;
  sequence: number;
}

function rollBody(row: RollRow): JsonValue {
  return { roll_id: row.roll_id, sides: row.sides, result: row.result, sequence: row.sequence } as unknown as JsonValue;
}

function nextRollSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_rng_rolls WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function configureRngSeed(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'only campaign members may configure the rng seed');
  if (forbidden) return forbidden;
  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may configure the rng seed' } };
  }

  const seed = body.seed;
  if (typeof seed !== 'string' || seed.length === 0) {
    return { status: 400, body: { error: 'seed must be a non-empty string' } };
  }

  const existing = db
    .prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?')
    .get(campaignId) as { seed: string } | undefined;
  if (existing) {
    return { status: 409, body: { error: 'rng seed already configured for this campaign' } };
  }

  db.prepare('INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)').run(campaignId, seed);

  return { status: 200, body: { seed, rolls: [] } as unknown as JsonValue };
}

export function appendRngRoll(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'only campaign members may append rng rolls');
  if (forbidden) return forbidden;

  const rollId = body.roll_id;
  if (typeof rollId !== 'string' || rollId.length === 0) {
    return { status: 400, body: { error: 'roll_id must be a non-empty string' } };
  }
  const sides = body.sides;
  if (!Number.isInteger(sides) || (sides as number) < 2 || (sides as number) > 100) {
    return { status: 400, body: { error: 'sides must be an integer from 2 through 100 inclusive' } };
  }

  const seedRow = db
    .prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?')
    .get(campaignId) as { seed: string } | undefined;
  if (!seedRow) {
    return { status: 409, body: { error: 'no rng seed configured for this campaign' } };
  }

  const existing = db
    .prepare('SELECT roll_id FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?')
    .get(campaignId, rollId);
  if (existing) {
    return { status: 409, body: { error: 'roll_id already used in this campaign rng ledger' } };
  }

  const sequence = nextRollSequence(db, campaignId);
  const result = computeRollResult(seedRow.seed, sequence, rollId, sides as number);

  db.prepare(
    'INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, rollId, sides, result);

  return { status: 201, body: rollBody({ roll_id: rollId, sides: sides as number, result, sequence }) };
}

export function getRngLedger(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'only campaign members may read the rng ledger');
  if (forbidden) return forbidden;

  const seedRow = db
    .prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?')
    .get(campaignId) as { seed: string } | undefined;

  const rolls = db
    .prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC')
    .all(campaignId) as unknown as RollRow[];

  return {
    status: 200,
    body: { seed: seedRow ? seedRow.seed : null, rolls: rolls.map(rollBody) } as unknown as JsonValue,
  };
}
