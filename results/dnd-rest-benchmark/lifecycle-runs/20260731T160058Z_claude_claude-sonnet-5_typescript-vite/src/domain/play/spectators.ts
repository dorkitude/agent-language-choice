/**
 * Read-only spectator access: the DM campaign owner mints spectator tickets,
 * and the resulting bearer token unlocks a scrubbed, repeat-stable campaign
 * projection with no member names, IDs, notes, chat, or ownership data.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, listMembers, requireNonEmptyString } from './shared.ts';

const SESSION_BEARER_RE = /^Bearer session-(.+)$/;
const SPECTATOR_BEARER_RE = /^Bearer spectator-(.+)$/;

interface SpectatorRow {
  campaign_id: string;
}

export function createSpectatorTicket(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign dm may create spectator tickets' } };
  }

  const spectatorId = requireNonEmptyString(body.spectator_id, 'spectator_id');
  if (isApiResult(spectatorId)) return spectatorId;

  const existing = db
    .prepare('SELECT spectator_id FROM play_campaign_spectators WHERE spectator_id = ?')
    .get(spectatorId);
  if (existing) {
    return { status: 409, body: { error: 'spectator_id already exists' } };
  }

  const token = `spectator-${spectatorId}`;
  db.prepare(
    'INSERT INTO play_campaign_spectators (campaign_id, spectator_id, token) VALUES (?, ?, ?)',
  ).run(campaignId, spectatorId, token);

  return { status: 201, body: { spectator_id: spectatorId, token } as unknown as JsonValue };
}

export function getSpectatorView(authHeader: string | undefined, campaignId: string): ApiResult {
  if (typeof authHeader !== 'string') {
    return { status: 401, body: { error: 'missing bearer token' } };
  }
  if (SESSION_BEARER_RE.test(authHeader)) {
    return { status: 403, body: { error: 'spectator view requires a spectator token' } };
  }
  const match = SPECTATOR_BEARER_RE.exec(authHeader);
  if (!match) {
    return { status: 401, body: { error: 'invalid bearer token' } };
  }
  const spectatorId = match[1];

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const ticket = db
    .prepare('SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?')
    .get(spectatorId) as SpectatorRow | undefined;
  if (!ticket) {
    return { status: 401, body: { error: 'invalid spectator token' } };
  }
  if (ticket.campaign_id !== campaignId) {
    return { status: 403, body: { error: 'spectator token is not valid for this campaign' } };
  }

  const partySize = listMembers(db, campaignId).length;

  return {
    status: 200,
    body: {
      campaign_id: campaign.id,
      name: campaign.name,
      status: campaign.status,
      party_size: partySize,
      story: campaign.story,
    } as unknown as JsonValue,
  };
}
