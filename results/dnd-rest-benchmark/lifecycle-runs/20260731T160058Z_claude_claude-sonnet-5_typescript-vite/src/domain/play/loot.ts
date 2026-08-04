/**
 * Campaign-scoped loot records: the DM opens loot, players vote on a
 * recipient character, and the DM assigns it exactly once. See shared.ts
 * for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  findMemberByCharacterId,
} from './shared.ts';
import { VALID_ITEM_IDS } from './inventory.ts';

type LootRow = {
  campaign_id: string;
  loot_id: string;
  item_id: string;
  quantity: number;
  status: string;
  recipient_character_id: string | null;
};

const LOOT_NOT_FOUND: ApiResult = { status: 404, body: { error: 'loot not found' } };

function findLoot(db: ReturnType<typeof getDb>, campaignId: string, lootId: string): LootRow | ApiResult {
  const loot = db
    .prepare(
      'SELECT campaign_id, loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?',
    )
    .get(campaignId, lootId) as LootRow | undefined;
  return loot ?? LOOT_NOT_FOUND;
}

function countVotesForRecipient(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  lootId: string,
  recipientCharacterId: string,
): number {
  const row = db
    .prepare(
      'SELECT COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?',
    )
    .get(campaignId, lootId, recipientCharacterId) as { count: number };
  return row.count;
}

export function createLoot(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create loot' } };
  }

  const lootId = body.loot_id;
  if (typeof lootId !== 'string' || lootId.length === 0) {
    return { status: 400, body: { error: 'loot_id must be a non-empty string' } };
  }

  const itemId = body.item_id;
  if (typeof itemId !== 'string' || !VALID_ITEM_IDS.has(itemId)) {
    return { status: 400, body: { error: 'item_id must be a valid catalog item' } };
  }

  if (!isValidIntInRange(body.quantity, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'quantity must be a positive integer' } };
  }
  const quantity = body.quantity as number;

  const existing = findLoot(db, campaignId, lootId);
  if (!isApiResult(existing)) {
    return { status: 409, body: { error: 'loot_id already exists in this campaign' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status, recipient_character_id) VALUES (?, ?, ?, ?, ?, NULL)',
  ).run(campaignId, lootId, itemId, quantity, 'open');

  return {
    status: 201,
    body: { loot_id: lootId, item_id: itemId, quantity, status: 'open' },
  };
}

export function voteLoot(
  authHeader: string | undefined,
  campaignId: string,
  lootId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (actor.role !== 'player') {
    return { status: 403, body: { error: 'only players may vote on loot' } };
  }

  const loot = findLoot(db, campaignId, lootId);
  if (isApiResult(loot)) return loot;

  const recipientCharacterId = body.recipient_character_id;
  if (typeof recipientCharacterId !== 'string' || recipientCharacterId.length === 0) {
    return { status: 400, body: { error: 'recipient_character_id must be a non-empty string' } };
  }

  const recipient = findMemberByCharacterId(db, campaignId, recipientCharacterId);
  if (isApiResult(recipient)) {
    return { status: 400, body: { error: 'recipient_character_id must be a character in this campaign' } };
  }

  const existingVote = db
    .prepare('SELECT recipient_character_id FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?')
    .get(campaignId, lootId, actor.username) as { recipient_character_id: string } | undefined;
  if (existingVote) {
    return { status: 409, body: { error: 'this identity has already voted on this loot' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)',
  ).run(campaignId, lootId, actor.username, recipientCharacterId);

  const votesForRecipient = countVotesForRecipient(db, campaignId, lootId, recipientCharacterId);

  return {
    status: 201,
    body: {
      loot_id: lootId,
      voter: actor.username,
      recipient_character_id: recipientCharacterId,
      votes_for_recipient: votesForRecipient,
    },
  };
}

export function assignLoot(authHeader: string | undefined, campaignId: string, lootId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may assign loot' } };
  }

  const loot = findLoot(db, campaignId, lootId);
  if (isApiResult(loot)) return loot;

  if (loot.status !== 'open') {
    return { status: 409, body: { error: 'loot is not open' } };
  }

  const tallies = db
    .prepare(
      'SELECT recipient_character_id, COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
    )
    .all(campaignId, lootId) as { recipient_character_id: string; count: number }[];

  if (tallies.length === 0) {
    return { status: 409, body: { error: 'loot has no votes' } };
  }

  tallies.sort((a, b) => b.count - a.count);
  if (tallies.length > 1 && tallies[0].count === tallies[1].count) {
    return { status: 409, body: { error: 'loot vote is tied' } };
  }

  const winner = tallies[0];
  const recipientCharacterId = winner.recipient_character_id;
  const votes = winner.count;

  const existingStack = db
    .prepare(
      'SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    )
    .get(campaignId, recipientCharacterId, loot.item_id) as { quantity: number } | undefined;
  const totalQuantity = (existingStack?.quantity ?? 0) + loot.quantity;

  if (existingStack) {
    db.prepare(
      'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    ).run(totalQuantity, campaignId, recipientCharacterId, loot.item_id);
  } else {
    db.prepare(
      'INSERT INTO play_campaign_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
    ).run(campaignId, recipientCharacterId, loot.item_id, totalQuantity);
  }

  db.prepare(
    "UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ? WHERE campaign_id = ? AND loot_id = ?",
  ).run(recipientCharacterId, campaignId, lootId);

  return {
    status: 200,
    body: {
      loot_id: lootId,
      recipient_character_id: recipientCharacterId,
      item_id: loot.item_id,
      quantity: loot.quantity,
      votes,
      status: 'assigned',
    },
  };
}

export function getLoot(authHeader: string | undefined, campaignId: string, lootId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const loot = findLoot(db, campaignId, lootId);
  if (isApiResult(loot)) return loot;

  const tallies = db
    .prepare(
      'SELECT recipient_character_id, COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id',
    )
    .all(campaignId, lootId) as { recipient_character_id: string; count: number }[];
  const votes: Record<string, number> = {};
  for (const tally of tallies) {
    votes[tally.recipient_character_id] = tally.count;
  }

  return {
    status: 200,
    body: {
      loot_id: loot.loot_id,
      item_id: loot.item_id,
      quantity: loot.quantity,
      status: loot.status,
      recipient_character_id: loot.recipient_character_id,
      votes,
    },
  };
}
