import { ServerResponse } from 'node:http';
import { SCHEMA_VERSION } from '../db.js';
import { sendJSON } from '../http-utils.js';
import {
  campaignCharacterExists,
  campaignEventExists,
  campaignExists,
  countCampaignCharacters,
  countCampaignEvents,
  countCampaignQuests,
  countCampaignSessions,
  countInventoryRows,
  countNPCs,
  createCampaign as createCampaignRecord,
  createCampaignCharacter,
  createCampaignEvent,
  getCampaign,
  getCampaignCharacters,
} from '../repository.js';
import { isNonEmptyString, isValidLevel } from '../validators.js';
import type { Campaign, CampaignCharacter, CampaignEvent } from '../types.js';

export function handleCampaignState(res: ServerResponse, params: Record<string, string>): void {
  const campaign = getCampaign(params.id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  sendJSON(res, 200, {
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: getCampaignCharacters(params.id),
    log_count: countCampaignEvents(params.id),
  });
}

export function handleCreateCampaign(res: ServerResponse, _params: unknown, body: unknown): void {
  const { id, name, dm } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(name) || !isNonEmptyString(dm)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (campaignExists(id)) {
    sendJSON(res, 409, { error: 'campaign already exists' });
    return;
  }
  const campaign: Campaign = { id, name, dm };
  createCampaignRecord(campaign);
  sendJSON(res, 201, campaign);
}

export function handleAddCampaignCharacter(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, name, level, class: className } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(id) ||
    !isNonEmptyString(name) ||
    !isNonEmptyString(className) ||
    !isValidLevel(level)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (campaignCharacterExists(id)) {
    sendJSON(res, 409, { error: 'character already exists' });
    return;
  }

  const character: CampaignCharacter = { id, name, level, class: className };
  createCampaignCharacter(params.id, character);
  sendJSON(res, 201, character);
}

export function handleAddCampaignEvent(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, kind, summary } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(kind)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (summary !== undefined && typeof summary !== 'string') {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (campaignEventExists(id)) {
    sendJSON(res, 409, { error: 'event already exists' });
    return;
  }

  const event: CampaignEvent = { id, kind, summary };
  createCampaignEvent(params.id, event);
  sendJSON(res, 201, { id, kind });
}

export function handleCampaignAudit(res: ServerResponse, params: Record<string, string>): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    campaign_id: params.id,
    events: countCampaignEvents(params.id),
    quests: countCampaignQuests(params.id),
    npcs: countNPCs(params.id),
    sessions: countCampaignSessions(params.id),
  });
}

export function handleCampaignExport(res: ServerResponse, params: Record<string, string>): void {
  const campaign = getCampaign(params.id);
  if (!campaign) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  sendJSON(res, 200, {
    campaign_id: campaign.id,
    name: campaign.name,
    characters: countCampaignCharacters(params.id),
    quests: countCampaignQuests(params.id),
    npcs: countNPCs(params.id),
    inventory_items: countInventoryRows(params.id),
    sessions: countCampaignSessions(params.id),
    schema_version: SCHEMA_VERSION,
  });
}
