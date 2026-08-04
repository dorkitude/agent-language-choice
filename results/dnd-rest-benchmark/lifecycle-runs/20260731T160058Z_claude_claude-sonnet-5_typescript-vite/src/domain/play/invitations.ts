/**
 * Campaign invitations: a DM invites a registered player identity to join
 * with a specific character_id, and only that player may accept.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { getUserRole } from '../auth.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  requireParticipant,
  requireNonEmptyString,
} from './shared.ts';

interface InvitationRow {
  sequence: number;
  invitation_id: string;
  username: string;
  character_id: string;
  status: string;
}

interface InvitationObject {
  invitation_id: string;
  username: string;
  character_id: string;
  status: string;
}

function toInvitationObject(row: InvitationRow): InvitationObject {
  return {
    invitation_id: row.invitation_id,
    username: row.username,
    character_id: row.character_id,
    status: row.status,
  };
}

export function createInvitation(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign dm may create invitations' } };
  }

  const invitationId = requireNonEmptyString(body.invitation_id, 'invitation_id');
  if (isApiResult(invitationId)) return invitationId;

  const username = requireNonEmptyString(body.username, 'username');
  if (isApiResult(username)) return username;

  const characterId = requireNonEmptyString(body.character_id, 'character_id');
  if (isApiResult(characterId)) return characterId;

  if (getUserRole(username) !== 'player') {
    return { status: 400, body: { error: 'username must be a registered player' } };
  }

  const existing = db
    .prepare('SELECT invitation_id FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?')
    .get(campaignId, invitationId);
  if (existing) {
    return { status: 409, body: { error: 'invitation_id already exists' } };
  }

  const activeForUser = db
    .prepare(
      "SELECT invitation_id FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'",
    )
    .get(campaignId, username);
  if (activeForUser) {
    return { status: 409, body: { error: 'an active invitation already exists for this user' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_invitations WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_invitations (campaign_id, sequence, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, invitationId, username, characterId, 'pending');

  return {
    status: 201,
    body: {
      invitation_id: invitationId,
      username,
      character_id: characterId,
      status: 'pending',
    } as unknown as JsonValue,
  };
}

export function acceptInvitation(
  authHeader: string | undefined,
  campaignId: string,
  invitationId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const row = db
    .prepare(
      'SELECT sequence, invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?',
    )
    .get(campaignId, invitationId) as InvitationRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'invitation not found' } };
  }

  if (actor.username !== row.username) {
    return { status: 403, body: { error: 'only the invited user may accept this invitation' } };
  }

  if (row.status !== 'pending') {
    return { status: 409, body: { error: 'invitation is no longer pending' } };
  }

  db.prepare(
    'UPDATE play_campaign_invitations SET status = ? WHERE campaign_id = ? AND invitation_id = ?',
  ).run('accepted', campaignId, invitationId);

  db.prepare(
    'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, row.username, row.character_id, row.username, 'adventurer');

  return {
    status: 200,
    body: {
      invitation_id: row.invitation_id,
      username: row.username,
      character_id: row.character_id,
      status: 'accepted',
    } as unknown as JsonValue,
  };
}

export function listInvitations(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  const isDm = campaign.owner === actor.username;

  const rows = db
    .prepare(
      'SELECT sequence, invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as InvitationRow[];

  if (isDm) {
    return { status: 200, body: { invitations: rows.map(toInvitationObject) } as unknown as JsonValue };
  }

  const own = rows.filter((row) => row.username === actor.username);
  if (own.length > 0) {
    return { status: 200, body: { invitations: own.map(toInvitationObject) } as unknown as JsonValue };
  }

  if (forbidden) return forbidden;

  return { status: 200, body: { invitations: [] } as unknown as JsonValue };
}
