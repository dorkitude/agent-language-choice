import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  campaignExists,
  characterExists,
  countCharactersByCampaign,
  countEventsByCampaign,
  countInventoryItemsByCampaign,
  countNpcsByCampaign,
  countQuestsByCampaign,
  countSessionsByCampaign,
  createCampaign,
  createCharacter,
  createEvent,
  eventExists,
  getCampaign,
  getCharactersByCampaign,
} from '../db.js';
import { isLevel, isNonEmptyString } from '../validation.js';
import { SCHEMA_VERSION } from '../constants.js';
import type { Campaign, Character, Event } from '../types.js';

export function handleGetCampaignState(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/state$/);
  if (!match) return false;
  const campaignId = match[1];
  const campaign = getCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const characters = getCharactersByCampaign(campaignId).map((c) => ({
    id: c.id,
    name: c.name,
    level: c.level,
    class: c.class,
  }));
  sendJson(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters,
    log_count: countEventsByCampaign(campaignId),
  });
  return true;
}

export function handleCreateCampaign(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name) || !isNonEmptyString(b.dm)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (campaignExists(b.id)) {
    sendError(res, 409, 'campaign already exists');
    return true;
  }
  const campaign: Campaign = { id: b.id, name: b.name, dm: b.dm };
  createCampaign(campaign);
  sendJson(res, 201, campaign);
  return true;
}

export function handleCreateCampaignCharacter(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/characters$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name) || !isLevel(b.level) || !isNonEmptyString(b.class)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (characterExists(b.id)) {
    sendError(res, 409, 'character already exists');
    return true;
  }
  const character: Character = {
    id: b.id,
    campaign_id: campaignId,
    name: b.name,
    level: b.level,
    class: b.class,
  };
  createCharacter(character);
  sendJson(res, 201, { id: character.id, name: character.name, level: character.level, class: character.class });
  return true;
}

export function handleCreateCampaignEvent(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/events$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.kind) || !isNonEmptyString(b.summary)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const eventId = b.id as string;
  if (eventExists(eventId)) {
    sendError(res, 409, 'event already exists');
    return true;
  }
  const event: Event = { id: eventId, campaign_id: campaignId, kind: b.kind, summary: b.summary };
  createEvent(event);
  sendJson(res, 201, { id: event.id, kind: event.kind });
  return true;
}

export function handleGetCampaignAudit(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/audit$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  sendJson(res, 200, {
    campaign_id: campaignId,
    events: countEventsByCampaign(campaignId),
    quests: countQuestsByCampaign(campaignId),
    npcs: countNpcsByCampaign(campaignId),
    sessions: countSessionsByCampaign(campaignId),
  });
  return true;
}

export function handleGetCampaignExport(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/export$/);
  if (!match) return false;
  const campaignId = match[1];
  const campaign = getCampaign(campaignId);
  if (!campaign) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  sendJson(res, 200, {
    campaign_id: campaign.id,
    name: campaign.name,
    characters: countCharactersByCampaign(campaignId),
    quests: countQuestsByCampaign(campaignId),
    npcs: countNpcsByCampaign(campaignId),
    inventory_items: countInventoryItemsByCampaign(campaignId),
    sessions: countSessionsByCampaign(campaignId),
    schema_version: SCHEMA_VERSION,
  });
  return true;
}
