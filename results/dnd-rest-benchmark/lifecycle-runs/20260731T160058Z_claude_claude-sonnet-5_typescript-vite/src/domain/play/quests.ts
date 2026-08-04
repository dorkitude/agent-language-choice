/**
 * Campaign quest records whose activation is gated by completed prerequisite
 * quests. See shared.ts for the ownership model.
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
  listMembers,
} from './shared.ts';
import { VALID_ITEM_IDS } from './inventory.ts';

const QUEST_COLUMNS = 'quest_id, title, depends_on_json, state, rewards_xp, rewards_items_json, rewards_awarded';

type QuestRow = {
  quest_id: string;
  title: string;
  depends_on_json: string;
  state: string;
  rewards_xp?: number | null;
  rewards_items_json?: string | null;
  rewards_awarded?: number;
};

function questBody(row: QuestRow): JsonValue {
  const body: Record<string, unknown> = {
    quest_id: row.quest_id,
    title: row.title,
    depends_on: JSON.parse(row.depends_on_json),
    state: row.state,
  };
  if (row.rewards_xp !== undefined && row.rewards_xp !== null) {
    body.rewards = { xp: row.rewards_xp, items: JSON.parse(row.rewards_items_json ?? '{}') };
  }
  return body as JsonValue;
}

function parseRewardsBody(body: JsonValue): { xp: number; items: Record<string, number> } | ApiResult {
  if (!isValidIntInRange(body.xp, 0, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'xp must be a nonnegative integer' } };
  }
  const itemsRaw = body.items;
  if (typeof itemsRaw !== 'object' || itemsRaw === null || Array.isArray(itemsRaw)) {
    return { status: 400, body: { error: 'items must be an object mapping catalog item IDs to quantities' } };
  }
  const items: Record<string, number> = {};
  for (const [itemId, quantity] of Object.entries(itemsRaw as Record<string, unknown>)) {
    if (!VALID_ITEM_IDS.has(itemId)) {
      return { status: 400, body: { error: `items key '${itemId}' must be a valid catalog item` } };
    }
    if (!isValidIntInRange(quantity, 1, Number.MAX_SAFE_INTEGER)) {
      return { status: 400, body: { error: 'items values must be positive integers' } };
    }
    items[itemId] = quantity as number;
  }
  return { xp: body.xp as number, items };
}

function nextQuestSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_quests WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createCampaignQuest(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create quests' } };
  }

  const questId = body.quest_id;
  if (typeof questId !== 'string' || questId.length === 0) {
    return { status: 400, body: { error: 'quest_id must be a non-empty string' } };
  }

  const title = body.title;
  if (typeof title !== 'string' || title.length === 0) {
    return { status: 400, body: { error: 'title must be a non-empty string' } };
  }

  const dependsOnRaw = body.depends_on;
  if (!Array.isArray(dependsOnRaw)) {
    return { status: 400, body: { error: 'depends_on must be an array of quest IDs' } };
  }
  const dependsOn: string[] = [];
  for (const dep of dependsOnRaw) {
    if (typeof dep !== 'string' || dep.length === 0) {
      return { status: 400, body: { error: 'depends_on must contain only non-empty quest ID strings' } };
    }
    dependsOn.push(dep);
  }
  if (new Set(dependsOn).size !== dependsOn.length) {
    return { status: 400, body: { error: 'depends_on must contain unique quest IDs' } };
  }
  if (dependsOn.includes(questId)) {
    return { status: 400, body: { error: 'depends_on cannot include the quest\'s own ID' } };
  }

  const existing = db
    .prepare('SELECT quest_id FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?')
    .get(campaignId, questId);
  if (existing) {
    return { status: 409, body: { error: 'quest_id already exists in this campaign' } };
  }

  for (const dep of dependsOn) {
    const depRow = db
      .prepare('SELECT quest_id FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?')
      .get(campaignId, dep);
    if (!depRow) {
      return { status: 400, body: { error: `depends_on quest '${dep}' does not exist in this campaign` } };
    }
  }

  const sequence = nextQuestSequence(db, campaignId);
  const dependsOnJson = JSON.stringify(dependsOn);
  db.prepare(
    'INSERT INTO play_campaign_quests (campaign_id, sequence, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, questId, title, dependsOnJson, 'locked');

  return {
    status: 201,
    body: questBody({ quest_id: questId, title, depends_on_json: dependsOnJson, state: 'locked' }),
  };
}

export function listCampaignQuests(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      `SELECT ${QUEST_COLUMNS} FROM play_campaign_quests WHERE campaign_id = ? ORDER BY sequence ASC`,
    )
    .all(campaignId) as QuestRow[];

  return { status: 200, body: { quests: rows.map((row) => questBody(row)) } };
}

export function setCampaignQuestState(
  authHeader: string | undefined,
  campaignId: string,
  questId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may change quest state' } };
  }

  const questRow = db
    .prepare(`SELECT ${QUEST_COLUMNS} FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?`)
    .get(campaignId, questId) as QuestRow | undefined;
  if (!questRow) {
    return { status: 404, body: { error: 'quest not found' } };
  }

  const newState = body.state;
  if (newState !== 'active' && newState !== 'completed') {
    return { status: 400, body: { error: "state must be exactly 'active' or 'completed'" } };
  }

  if (newState === 'active') {
    if (questRow.state !== 'locked') {
      return { status: 409, body: { error: 'quest must be locked to become active' } };
    }
    const dependsOn = JSON.parse(questRow.depends_on_json) as string[];
    for (const dep of dependsOn) {
      const depRow = db
        .prepare('SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?')
        .get(campaignId, dep) as { state: string } | undefined;
      if (!depRow || depRow.state !== 'completed') {
        return { status: 409, body: { error: 'all prerequisite quests must be completed' } };
      }
    }
  } else {
    if (questRow.state !== 'active') {
      return { status: 409, body: { error: 'quest must be active to become completed' } };
    }
  }

  db.prepare('UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?').run(
    newState,
    campaignId,
    questId,
  );

  return { status: 200, body: questBody({ ...questRow, state: newState }) };
}

export function configureQuestRewards(
  authHeader: string | undefined,
  campaignId: string,
  questId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may configure quest rewards' } };
  }

  const questRow = db
    .prepare(`SELECT ${QUEST_COLUMNS} FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?`)
    .get(campaignId, questId) as QuestRow | undefined;
  if (!questRow) {
    return { status: 404, body: { error: 'quest not found' } };
  }

  if (questRow.state === 'completed') {
    return { status: 409, body: { error: 'quest rewards cannot be configured once the quest is completed' } };
  }

  const parsed = parseRewardsBody(body);
  if (isApiResult(parsed)) return parsed;

  const rewardsItemsJson = JSON.stringify(parsed.items);
  db.prepare(
    'UPDATE play_campaign_quests SET rewards_xp = ?, rewards_items_json = ? WHERE campaign_id = ? AND quest_id = ?',
  ).run(parsed.xp, rewardsItemsJson, campaignId, questId);

  return {
    status: 200,
    body: questBody({ ...questRow, rewards_xp: parsed.xp, rewards_items_json: rewardsItemsJson }),
  };
}

export function awardQuestRewards(authHeader: string | undefined, campaignId: string, questId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may award quest rewards' } };
  }

  const questRow = db
    .prepare(`SELECT ${QUEST_COLUMNS} FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?`)
    .get(campaignId, questId) as QuestRow | undefined;
  if (!questRow) {
    return { status: 404, body: { error: 'quest not found' } };
  }

  if (questRow.state !== 'completed' || questRow.rewards_xp === null || questRow.rewards_xp === undefined) {
    return { status: 409, body: { error: 'quest must be completed with rewards configured to award them' } };
  }
  if (questRow.rewards_awarded) {
    return { status: 409, body: { error: 'quest rewards have already been awarded' } };
  }

  const xp = questRow.rewards_xp;
  const items = JSON.parse(questRow.rewards_items_json ?? '{}') as Record<string, number>;
  const itemsJson = JSON.stringify(items);

  const members = listMembers(db, campaignId);
  const insertGrant = db.prepare(
    'INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)',
  );
  const getStack = db.prepare(
    'SELECT quantity FROM play_campaign_inventory_stacks WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
  );
  const updateStack = db.prepare(
    'UPDATE play_campaign_inventory_stacks SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
  );
  const insertStack = db.prepare(
    'INSERT INTO play_campaign_inventory_stacks (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
  );
  for (const member of members) {
    insertGrant.run(campaignId, questId, member.character_id, xp, itemsJson);
    for (const [itemId, quantity] of Object.entries(items)) {
      const existing = getStack.get(campaignId, member.character_id, itemId) as { quantity: number } | undefined;
      if (existing) {
        updateStack.run(existing.quantity + quantity, campaignId, member.character_id, itemId);
      } else {
        insertStack.run(campaignId, member.character_id, itemId, quantity);
      }
    }
  }

  db.prepare('UPDATE play_campaign_quests SET rewards_awarded = 1 WHERE campaign_id = ? AND quest_id = ?').run(
    campaignId,
    questId,
  );

  return { status: 201, body: { quest_id: questId, awarded: true, xp, items } };
}

export function getCharacterQuestRewards(
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

  const rows = db
    .prepare('SELECT xp, items_json FROM play_campaign_quest_reward_grants WHERE campaign_id = ? AND character_id = ?')
    .all(campaignId, characterId) as { xp: number; items_json: string }[];

  let totalXp = 0;
  const totalItems: Record<string, number> = {};
  for (const row of rows) {
    totalXp += row.xp;
    const items = JSON.parse(row.items_json) as Record<string, number>;
    for (const [itemId, quantity] of Object.entries(items)) {
      totalItems[itemId] = (totalItems[itemId] ?? 0) + quantity;
    }
  }

  return { status: 200, body: { character_id: characterId, xp: totalXp, items: totalItems } };
}
