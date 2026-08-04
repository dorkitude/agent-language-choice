/**
 * Scene lifecycle within a play campaign: create, enter, close, and read the
 * currently-open scene. Only the campaign owner (DM) may mutate scenes.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  findScene,
  requireParticipant,
  nextSequence,
  insertEvent,
  requireNonEmptyString,
} from './shared.ts';

export function createScene(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may create a scene' } };
  }

  const id = requireNonEmptyString(body.id, 'id');
  if (isApiResult(id)) return id;

  const name = requireNonEmptyString(body.name, 'name');
  if (isApiResult(name)) return name;

  const existing = db
    .prepare('SELECT id FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?')
    .get(campaignId, id);
  if (existing) {
    return { status: 409, body: { error: 'scene id already exists' } };
  }

  db.prepare('INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)').run(
    campaignId,
    id,
    name,
    'open',
  );

  return { status: 201, body: { id, name, status: 'open' } };
}

export function enterScene(authHeader: string | undefined, campaignId: string, sceneId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may enter a scene' } };
  }

  const scene = findScene(db, campaignId, sceneId);
  if (isApiResult(scene)) return scene;

  if (scene.status !== 'open') {
    return { status: 409, body: { error: 'closed scenes may not be entered' } };
  }

  db.prepare('UPDATE play_campaigns SET current_scene_id = ? WHERE id = ?').run(sceneId, campaignId);

  const sequence = nextSequence(db, campaignId);
  insertEvent(db, campaignId, sequence, 'scene', actor.username, sceneId);

  return { status: 200, body: { current_scene_id: sceneId, name: scene.name } };
}

export function closeScene(authHeader: string | undefined, campaignId: string, sceneId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may close a scene' } };
  }

  const scene = findScene(db, campaignId, sceneId);
  if (isApiResult(scene)) return scene;

  db.prepare('UPDATE play_campaign_scenes SET status = ? WHERE campaign_id = ? AND id = ?').run(
    'closed',
    campaignId,
    sceneId,
  );

  if (campaign.current_scene_id === sceneId) {
    db.prepare('UPDATE play_campaigns SET current_scene_id = NULL WHERE id = ?').run(campaignId);
  }

  return { status: 200, body: { id: sceneId, status: 'closed' } };
}

export function getCurrentScene(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (!campaign.current_scene_id) {
    return { status: 404, body: { error: 'no current scene set' } };
  }

  const scene = findScene(db, campaignId, campaign.current_scene_id);
  if (isApiResult(scene)) return scene;

  if (scene.status !== 'open') {
    return { status: 404, body: { error: 'no current scene set' } };
  }

  return { status: 200, body: { id: scene.id, name: scene.name, status: scene.status } };
}
