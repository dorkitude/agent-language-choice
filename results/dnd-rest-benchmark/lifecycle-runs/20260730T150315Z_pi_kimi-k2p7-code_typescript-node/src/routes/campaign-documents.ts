import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  getCampaignDocument,
  getPlayCampaign,
  getPlayMembershipByCampaignAndUser,
  setCampaignDocument,
} from '../repository.js';
import { requireActor } from '../play-auth.js';
import { isString } from '../validators.js';

/**
 * Campaign documents belong to a play campaign. The owner (DM) can read and
 * write both the public `story` and private `dm_notes`; players can only read
 * the public `story`.
 */
export function handleGetCampaignDocument(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaign(params.id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const isOwner = campaign.owner === actor.username;
  const isMember = getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isOwner && !isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const doc = getCampaignDocument(params.id) ?? { story: '', dm_notes: '' };
  if (isOwner) {
    sendJSON(res, 200, { story: doc.story, dm_notes: doc.dm_notes });
  } else {
    sendJSON(res, 200, { story: doc.story });
  }
}

export function handleUpdateCampaignDocument(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaign(params.id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  const { story, dm_notes } = body as Record<string, unknown>;
  if (!isString(story) || !isString(dm_notes)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  setCampaignDocument(params.id, { story, dm_notes });
  sendJSON(res, 200, { story, dm_notes });
}
