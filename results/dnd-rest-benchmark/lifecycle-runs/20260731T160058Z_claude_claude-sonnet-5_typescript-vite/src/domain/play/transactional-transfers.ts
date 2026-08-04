/**
 * Campaign-scoped transactional currency transfers. Unlike the plain
 * character-to-character transfer in currency.ts, this endpoint supports a
 * `simulate_failure` flag used to prove that a failed compound mutation
 * leaves no partial debit, credit, or transfer record: all validation and
 * balance computation happens before any write, and the two balance updates
 * plus the transfer record insert are wrapped in a single SQLite
 * transaction so they commit or roll back together.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  findMemberByCharacterId,
  requireParticipant,
  resolveCharacterOwner,
} from './shared.ts';

interface TransactionalTransferRow {
  sequence: number;
  from_character_id: string;
  to_character_id: string;
  amount: number;
  from_gold: number;
  to_gold: number;
}

function toTransferBody(row: TransactionalTransferRow): JsonValue {
  return {
    from_character_id: row.from_character_id,
    to_character_id: row.to_character_id,
    amount: row.amount,
    from_gold: row.from_gold,
    to_gold: row.to_gold,
    sequence: row.sequence,
  } as unknown as JsonValue;
}

function nextTransactionalTransferSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ?',
    )
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createTransactionalTransfer(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const fromCharacterId = body.from_character_id;
  const toCharacterId = body.to_character_id;
  if (typeof fromCharacterId !== 'string' || fromCharacterId.length === 0) {
    return { status: 400, body: { error: 'from_character_id must be a non-empty string' } };
  }
  if (typeof toCharacterId !== 'string' || toCharacterId.length === 0 || toCharacterId === fromCharacterId) {
    return { status: 400, body: { error: 'to_character_id must be a different character in the campaign' } };
  }
  if (!isValidIntInRange(body.amount, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'amount must be a positive integer' } };
  }
  if (body.simulate_failure !== undefined && typeof body.simulate_failure !== 'boolean') {
    return { status: 400, body: { error: 'simulate_failure must be a boolean' } };
  }
  const amount = body.amount as number;
  const simulateFailure = body.simulate_failure === true;

  const source = findMemberByCharacterId(db, campaignId, fromCharacterId);
  if (isApiResult(source)) {
    return { status: 400, body: { error: 'from_character_id is not a valid character in this campaign' } };
  }
  const destination = findMemberByCharacterId(db, campaignId, toCharacterId);
  if (isApiResult(destination)) {
    return { status: 400, body: { error: 'to_character_id is not a valid character in this campaign' } };
  }

  const owner = resolveCharacterOwner(db, campaignId, fromCharacterId);
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the owner of from_character_id may create this transfer' } };
  }

  if (source.gold < amount) {
    return { status: 409, body: { error: 'insufficient gold' } };
  }

  const fromGold = source.gold - amount;
  const toGold = destination.gold + amount;

  if (simulateFailure) {
    return { status: 500, body: { error: 'simulated failure' } };
  }

  db.exec('BEGIN');
  try {
    db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
      fromGold,
      campaignId,
      fromCharacterId,
    );
    db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
      toGold,
      campaignId,
      toCharacterId,
    );

    const sequence = nextTransactionalTransferSequence(db, campaignId);
    db.prepare(
      'INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)',
    ).run(campaignId, sequence, fromCharacterId, toCharacterId, amount, fromGold, toGold);

    db.exec('COMMIT');

    return {
      status: 201,
      body: toTransferBody({
        sequence,
        from_character_id: fromCharacterId,
        to_character_id: toCharacterId,
        amount,
        from_gold: fromGold,
        to_gold: toGold,
      }),
    };
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

export function listTransactionalTransfers(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT sequence, from_character_id, to_character_id, amount, from_gold, to_gold FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as TransactionalTransferRow[];

  return { status: 200, body: { transfers: rows.map(toTransferBody) } };
}
