import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  createScene,
  getPlayCampaign,
  getPlayMembershipByCampaignAndUser,
  getScene,
  sceneExists,
  updatePlayCampaignCurrentScene,
  updateSceneStatus,
} from '../repository.js';
import { requireActor } from '../play-auth.js';
import { isNonEmptyString } from '../validators.js';
import type { Scene } from '../types.js';

function getPlayCampaignOr404(res: ServerResponse, id: string) {
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return null;
  }
  return campaign;
}

function requireOwner(
  req: IncomingMessage,
  res: ServerResponse,
  campaign: { owner: string },
) {
  const actor = requireActor(req, res);
  if (!actor) return null;
  if (campaign.owner !== actor.username) {
    sendJSON(res, 403, { error: 'forbidden' });
    return null;
  }
  return actor;
}

export function handleCreateScene(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const actor = requireOwner(req, res, campaign);
  if (!actor) return;

  const { id, name } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(name)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (sceneExists(id, params.id)) {
    sendJSON(res, 409, { error: 'scene already exists' });
    return;
  }

  const scene: Scene = {
    id,
    campaign_id: params.id,
    name,
    status: 'open',
  };
  createScene(scene);
  sendJSON(res, 201, { id: scene.id, name: scene.name, status: scene.status });
}

export function handleEnterScene(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const actor = requireOwner(req, res, campaign);
  if (!actor) return;

  const scene = getScene(params.scene_id, params.id);
  if (!scene) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  if (scene.status === 'closed') {
    sendJSON(res, 409, { error: 'scene is closed' });
    return;
  }

  updatePlayCampaignCurrentScene(params.id, scene.id);
  sendJSON(res, 200, { current_scene_id: scene.id, name: scene.name });
}

export function handleCloseScene(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const actor = requireOwner(req, res, campaign);
  if (!actor) return;

  const scene = getScene(params.scene_id, params.id);
  if (!scene) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  updateSceneStatus(scene.id, params.id, 'closed');
  sendJSON(res, 200, { id: scene.id, status: 'closed' });
}

export function handleGetCurrentScene(
  res: ServerResponse,
  params: Record<string, string>,
  _body: unknown,
  req: IncomingMessage,
): void {
  const actor = requireActor(req, res);
  if (!actor) return;

  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const isOwner = campaign.owner === actor.username;
  const isMember = getPlayMembershipByCampaignAndUser(params.id, actor.username) !== null;
  if (!isOwner && !isMember) {
    sendJSON(res, 403, { error: 'forbidden' });
    return;
  }

  if (!campaign.current_scene_id) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const scene = getScene(campaign.current_scene_id, params.id);
  if (!scene || scene.status !== 'open') {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, { id: scene.id, name: scene.name, status: scene.status });
}
