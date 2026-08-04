/**
 * Per-character gold balances and campaign-local character-to-character
 * transfers within a play campaign. See shared.ts for the ownership model.
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
  nextTransferId,
} from './shared.ts';

export function getCharacterCurrency(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  return { status: 200, body: { character_id: characterId, gold: member.gold } };
}

export function transferCurrency(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const source = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(source)) return source;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the source character owner may transfer gold' } };
  }

  const toCharacterId = body.to_character_id;
  if (typeof toCharacterId !== 'string' || toCharacterId.length === 0 || toCharacterId === characterId) {
    return { status: 400, body: { error: 'to_character_id must be a different character in the campaign' } };
  }

  const destination = findMemberByCharacterId(db, campaignId, toCharacterId);
  if (isApiResult(destination)) {
    return { status: 400, body: { error: 'to_character_id must be a different character in the campaign' } };
  }

  if (!isValidIntInRange(body.gold, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'gold must be a positive integer' } };
  }
  const amount = body.gold as number;

  if (source.gold < amount) {
    return { status: 409, body: { error: 'insufficient gold' } };
  }

  const fromGold = source.gold - amount;
  const toGold = destination.gold + amount;

  db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
    fromGold,
    campaignId,
    characterId,
  );
  db.prepare('UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?').run(
    toGold,
    campaignId,
    toCharacterId,
  );

  const transferId = nextTransferId(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, transferId, characterId, toCharacterId, amount);

  return {
    status: 201,
    body: {
      from_character_id: characterId,
      to_character_id: toCharacterId,
      gold: amount,
      from_gold: fromGold,
      to_gold: toGold,
      transfer_id: transferId,
    },
  };
}
