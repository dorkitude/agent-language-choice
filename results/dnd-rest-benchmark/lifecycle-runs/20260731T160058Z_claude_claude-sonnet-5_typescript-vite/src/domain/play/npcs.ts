/**
 * Campaign-scoped NPC records: the DM tracks a private agenda alongside a
 * player-visible public status. See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

type NpcRow = {
  campaign_id: string;
  npc_id: string;
  name: string;
  agenda: string;
  public_status: string;
};

const NPC_NOT_FOUND: ApiResult = { status: 404, body: { error: 'npc not found' } };

function findNpc(db: ReturnType<typeof getDb>, campaignId: string, npcId: string): NpcRow | ApiResult {
  const npc = db
    .prepare('SELECT campaign_id, npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?')
    .get(campaignId, npcId) as NpcRow | undefined;
  return npc ?? NPC_NOT_FOUND;
}

export function createCampaignNpc(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create npcs' } };
  }

  const npcId = body.npc_id;
  if (typeof npcId !== 'string' || npcId.length === 0) {
    return { status: 400, body: { error: 'npc_id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const agenda = body.agenda;
  if (typeof agenda !== 'string' || agenda.length === 0) {
    return { status: 400, body: { error: 'agenda must be a non-empty string' } };
  }

  const publicStatus = body.public_status;
  if (typeof publicStatus !== 'string' || publicStatus.length === 0) {
    return { status: 400, body: { error: 'public_status must be a non-empty string' } };
  }

  const existing = findNpc(db, campaignId, npcId);
  if (!isApiResult(existing)) {
    return { status: 409, body: { error: 'npc_id already exists in this campaign' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, npcId, name, agenda, publicStatus);

  return {
    status: 201,
    body: { npc_id: npcId, name, agenda, public_status: publicStatus },
  };
}

export function updateCampaignNpcAgenda(
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may update npc agendas' } };
  }

  const agenda = body.agenda;
  if (typeof agenda !== 'string' || agenda.length === 0) {
    return { status: 400, body: { error: 'agenda must be a non-empty string' } };
  }

  const publicStatus = body.public_status;
  if (typeof publicStatus !== 'string' || publicStatus.length === 0) {
    return { status: 400, body: { error: 'public_status must be a non-empty string' } };
  }

  const npc = findNpc(db, campaignId, npcId);
  if (isApiResult(npc)) return npc;

  db.prepare(
    'UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?',
  ).run(agenda, publicStatus, campaignId, npcId);

  return {
    status: 200,
    body: { npc_id: npc.npc_id, name: npc.name, agenda, public_status: publicStatus },
  };
}

export function getCampaignNpc(authHeader: string | undefined, campaignId: string, npcId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const npc = findNpc(db, campaignId, npcId);
  if (isApiResult(npc)) return npc;

  if (actor.username === campaign.owner) {
    return {
      status: 200,
      body: { npc_id: npc.npc_id, name: npc.name, agenda: npc.agenda, public_status: npc.public_status },
    };
  }

  return {
    status: 200,
    body: { npc_id: npc.npc_id, name: npc.name, public_status: npc.public_status },
  };
}

type DialogueRow = {
  dialogue_id: string;
  speaker: string;
  text: string;
  visibility: string;
};

function nextDialogueSequence(db: ReturnType<typeof getDb>, campaignId: string, npcId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?',
    )
    .get(campaignId, npcId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function addNpcDialogue(
  authHeader: string | undefined,
  campaignId: string,
  npcId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may append npc dialogue' } };
  }

  const npc = findNpc(db, campaignId, npcId);
  if (isApiResult(npc)) return npc;

  const dialogueId = body.dialogue_id;
  if (typeof dialogueId !== 'string' || dialogueId.length === 0) {
    return { status: 400, body: { error: 'dialogue_id must be a non-empty string' } };
  }

  const speaker = body.speaker;
  if (typeof speaker !== 'string' || speaker.length === 0) {
    return { status: 400, body: { error: 'speaker must be a non-empty string' } };
  }

  const text = body.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }

  const visibility = body.visibility;
  if (visibility !== 'public' && visibility !== 'private') {
    return { status: 400, body: { error: "visibility must be exactly 'public' or 'private'" } };
  }

  const existing = db
    .prepare(
      'SELECT dialogue_id FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?',
    )
    .get(campaignId, npcId, dialogueId);
  if (existing) {
    return { status: 409, body: { error: 'dialogue_id already exists for this npc' } };
  }

  const sequence = nextDialogueSequence(db, campaignId, npcId);
  db.prepare(
    `INSERT INTO play_campaign_npc_dialogue
       (campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(campaignId, npcId, sequence, dialogueId, speaker, text, visibility);

  return {
    status: 201,
    body: { dialogue_id: dialogueId, speaker, text, visibility },
  };
}

export function getNpcDialogue(authHeader: string | undefined, campaignId: string, npcId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const npc = findNpc(db, campaignId, npcId);
  if (isApiResult(npc)) return npc;

  const rows = db
    .prepare(
      `SELECT dialogue_id, speaker, text, visibility
       FROM play_campaign_npc_dialogue
       WHERE campaign_id = ? AND npc_id = ?
       ORDER BY sequence ASC`,
    )
    .all(campaignId, npcId) as DialogueRow[];

  const entries = actor.username === campaign.owner ? rows : rows.filter((row) => row.visibility === 'public');

  return {
    status: 200,
    body: {
      npc_id: npc.npc_id,
      entries: entries.map((entry) => ({
        dialogue_id: entry.dialogue_id,
        speaker: entry.speaker,
        text: entry.text,
        visibility: entry.visibility,
      })),
    },
  };
}
