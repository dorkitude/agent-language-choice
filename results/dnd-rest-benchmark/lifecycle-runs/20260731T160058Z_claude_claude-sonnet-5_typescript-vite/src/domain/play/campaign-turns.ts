/**
 * Play-campaign lifecycle and turn flow: creation, joining, starting,
 * whose-turn-is-it queries, nudging, player actions, DM resolutions, and the
 * shared campaign document (story + private DM notes).
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { getUserRole } from '../auth.ts';
import { isValidIntInRange } from '../../validation.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  listMembers,
  requireParticipant,
  nextSequence,
  insertEvent,
  recentEvents,
  requireNonEmptyString,
  TURN_DEADLINE_NUDGES,
} from './shared.ts';
import { hasActivePower } from './delegations.ts';

export function createPlayCampaign(authHeader: string | undefined, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;
  if (actor.role !== 'dm') {
    return { status: 403, body: { error: 'only a dm may create a play campaign' } };
  }

  const id = requireNonEmptyString(body.id, 'id');
  if (isApiResult(id)) return id;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  const maxPlayers = body.max_players;
  if (!isValidIntInRange(maxPlayers, 1, 20)) {
    return { status: 400, body: { error: 'max_players must be an integer from 1 through 20' } };
  }

  const db = getDb();
  const existing = db.prepare('SELECT id FROM play_campaigns WHERE id = ?').get(id);
  if (existing) {
    return { status: 409, body: { error: 'play campaign id already exists' } };
  }

  db.prepare(
    'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
  ).run(id, name, actor.username, 'lobby', maxPlayers);

  return {
    status: 201,
    body: { id, name, owner: actor.username, status: 'lobby', max_players: maxPlayers },
  };
}

export function joinPlayCampaign(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;
  if (actor.role !== 'player') {
    return { status: 403, body: { error: 'only a player may join a play campaign' } };
  }

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const characterId = requireNonEmptyString(body.character_id, 'character_id');
  if (isApiResult(characterId)) return characterId;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  const characterClass = requireNonEmptyString(body.class, 'class');
  if (isApiResult(characterClass)) return characterClass;

  const members = listMembers(db, campaignId);
  const alreadyMember = members.some((member) => member.username === actor.username);
  const duplicateCharacter = members.some((member) => member.character_id === characterId);
  const partyFull = members.length >= campaign.max_players;
  if (alreadyMember || duplicateCharacter || partyFull) {
    return { status: 409, body: { error: 'cannot join play campaign' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, actor.username, characterId, name, characterClass);

  return {
    status: 201,
    body: { username: actor.username, character_id: characterId, name, class: characterClass },
  };
}

export function startPlayCampaign(
  authHeader: string | undefined,
  campaignId: string,
  _body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the dm owner may start the campaign' } };
  }

  const members = listMembers(db, campaignId);
  if (campaign.status !== 'lobby' || members.length < 2) {
    return { status: 409, body: { error: 'campaign cannot be started' } };
  }

  const currentActor = members[0].username;
  db.prepare(
    'UPDATE play_campaigns SET status = ?, current_actor = ?, turn_number = ?, turn_nudge_count = 0, phase = ? WHERE id = ?',
  ).run('active', currentActor, 1, 'player', campaignId);

  return {
    status: 200,
    body: { id: campaignId, status: 'active', current_actor: currentActor, turn_number: 1 },
  };
}

export function getPlayCampaignTurn(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a member of this play campaign');
  if (forbidden) return forbidden;

  const phase =
    campaign.phase ??
    (campaign.current_actor
      ? getUserRole(campaign.current_actor) ??
        (campaign.current_actor === campaign.owner ? 'dm' : 'player')
      : campaign.status);

  const members = listMembers(db, campaignId);
  const queue = members.flatMap((member) => [member.username, campaign.owner]);

  const overdue = campaign.turn_nudge_count >= TURN_DEADLINE_NUDGES;

  return {
    status: 200,
    body: {
      campaign_id: campaign.id,
      current_actor: campaign.current_actor,
      phase,
      turn_number: campaign.turn_number,
      queue,
      overdue,
      logical_deadline: TURN_DEADLINE_NUDGES,
    },
  };
}

export function nudgePlayCampaignTurn(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may nudge the turn' } };
  }

  if (!campaign.current_actor) {
    return { status: 409, body: { error: 'no active turn to nudge' } };
  }

  const message = requireNonEmptyString(body.message, 'message');
  if (isApiResult(message)) return message;

  const nudgeCount = campaign.turn_nudge_count + 1;
  db.prepare('UPDATE play_campaigns SET turn_nudge_count = ? WHERE id = ?').run(nudgeCount, campaignId);

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'nudge', actor.username, message);

  return {
    status: 201,
    body: {
      actor: actor.username,
      target: campaign.current_actor,
      message,
      nudge_count: nudgeCount,
    },
  };
}

export function getPlayerTurnContext(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (actor.role !== 'player') {
    return { status: 403, body: { error: 'player role required' } };
  }

  const member = listMembers(db, campaignId).find((m) => m.username === actor.username);
  if (!member) {
    return { status: 403, body: { error: 'not a campaign member' } };
  }

  const events = recentEvents(db, campaignId);

  return {
    status: 200,
    body: {
      is_my_turn: campaign.current_actor === actor.username,
      current_actor: campaign.current_actor,
      character: { id: member.character_id, name: member.name },
      recent_events: events.map((event) => ({
        sequence: event.sequence,
        kind: event.kind,
        actor: event.actor,
        text: event.text,
      })),
    },
  };
}

export function getGmStatus(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the dm owner may view gm status' } };
  }

  const members = listMembers(db, campaignId);
  const events = recentEvents(db, campaignId, 10);

  return {
    status: 200,
    body: {
      needs_attention: campaign.current_actor === campaign.owner,
      current_actor: campaign.current_actor,
      party: members.map((member) => ({
        username: member.username,
        character_id: member.character_id,
        name: member.name,
        class: member.class,
      })),
      recent_events: events.map((event) => ({
        sequence: event.sequence,
        kind: event.kind,
        actor: event.actor,
        text: event.text,
      })),
    },
  };
}

export function submitPlayerAction(
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

  if (actor.role !== 'player' || campaign.current_actor !== actor.username) {
    return { status: 409, body: { error: 'only the active player may submit an action' } };
  }

  const type = requireNonEmptyString(body.type, 'type');
  if (isApiResult(type)) return type;

  const text = requireNonEmptyString(body.text, 'text');
  if (isApiResult(text)) return text;

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'action', actor.username, text, type);

  db.prepare('UPDATE play_campaigns SET current_actor = ?, turn_nudge_count = 0, phase = ? WHERE id = ?').run(
    campaign.owner,
    'gm',
    campaignId,
  );

  return {
    status: 201,
    body: {
      sequence,
      kind: 'action',
      actor: actor.username,
      type,
      text,
      next_actor: 'dm',
    },
  };
}

export function submitResolution(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner || campaign.current_actor !== campaign.owner) {
    return { status: 409, body: { error: 'only the owner may resolve on their turn' } };
  }

  const text = requireNonEmptyString(body.text, 'text');
  if (isApiResult(text)) return text;

  const members = listMembers(db, campaignId);
  const currentTurnNumber = campaign.turn_number ?? 0;
  const nextActor =
    (currentTurnNumber < 2 ? members[1]?.username : members[0]?.username) ?? campaign.owner;

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'resolution', 'dm', text);

  const turnNumber = (campaign.turn_number ?? 0) + 1;
  db.prepare(
    'UPDATE play_campaigns SET current_actor = ?, turn_number = ?, turn_nudge_count = 0, phase = ? WHERE id = ?',
  ).run(nextActor, turnNumber, 'player', campaignId);

  return {
    status: 201,
    body: {
      sequence,
      kind: 'resolution',
      actor: 'dm',
      text,
      next_actor: nextActor,
      turn_number: turnNumber,
    },
  };
}

export function updateCampaignDocument(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the owner may update the campaign document' } };
  }

  const story = body.story;
  if (typeof story !== 'string') {
    return { status: 400, body: { error: 'story must be a string' } };
  }

  const dmNotes = body.dm_notes;
  if (typeof dmNotes !== 'string') {
    return { status: 400, body: { error: 'dm_notes must be a string' } };
  }

  db.prepare('UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?').run(story, dmNotes, campaignId);

  return { status: 200, body: { story, dm_notes: dmNotes } };
}

export function getCampaignDocument(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = campaign.owner === actor.username;
  if (!isOwner) {
    const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
    if (forbidden) return forbidden;
  }

  if (isOwner) {
    return {
      status: 200,
      body: { story: campaign.story, dm_notes: campaign.dm_notes },
    };
  }

  return { status: 200, body: { story: campaign.story } };
}

const DM_NEXT_STEPS = ['configure-safety', 'invite-players', 'start-campaign'];
const PLAYER_NEXT_STEPS = ['review-party', 'take-turn', 'submit-action'];

export function getCampaignOnboarding(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a member of this play campaign');
  if (forbidden) return forbidden;

  const isOwner = campaign.owner === actor.username;
  if (isOwner) {
    return {
      status: 200,
      body: { role: 'dm', next_steps: DM_NEXT_STEPS, can_mutate: true },
    };
  }

  return {
    status: 200,
    body: { role: 'player', next_steps: PLAYER_NEXT_STEPS, can_mutate: true },
  };
}

export function addNarration(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const isOwner = actor.username === campaign.owner;
  const isDelegatedNarrator = !isOwner && hasActivePower(db, campaignId, actor.username, 'narrate');
  if (actor.role !== 'dm' && !isDelegatedNarrator) {
    return { status: 403, body: { error: 'only a dm or a delegated narrator may narrate' } };
  }

  const text = requireNonEmptyString(body.text, 'text');
  if (isApiResult(text)) return text;

  const narratorActor = isDelegatedNarrator ? actor.username : 'dm';
  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'narration', narratorActor, text);

  return {
    status: 201,
    body: { sequence, kind: 'narration', actor: narratorActor, text },
  };
}

export function addChatMessage(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a member of this play campaign');
  if (forbidden) return forbidden;

  const text = requireNonEmptyString(body.text, 'text');
  if (isApiResult(text)) return text;

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'chat', actor.username, text);

  return {
    status: 201,
    body: { sequence, kind: 'chat', actor: actor.username, text, current_actor: campaign.current_actor },
  };
}
