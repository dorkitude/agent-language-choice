import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import {
  campaignExists,
  countFactionsByCampaign,
  countFriendlyNpcsByCampaign,
  countNpcsByCampaign,
  createFaction,
  createNpc,
  factionExists,
  getFaction,
  npcExists,
} from '../db.js';
import { isDisposition, isNonEmptyString, isStance } from '../validation.js';
import type { Faction, Npc } from '../types.js';

export function handleCreateFaction(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/factions$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name) || !isStance(b.stance)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (factionExists(b.id)) {
    sendError(res, 409, 'faction already exists');
    return true;
  }
  const faction: Faction = {
    id: b.id,
    campaign_id: campaignId,
    name: b.name,
    stance: b.stance,
  };
  createFaction(faction);
  sendJson(res, 201, { id: faction.id, name: faction.name, stance: faction.stance });
  return true;
}

export function handleCreateNpc(pathname: string, body: unknown, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/npcs$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  const b = body as any;
  if (!b || !isNonEmptyString(b.id) || !isNonEmptyString(b.name) || !isNonEmptyString(b.faction_id) || !isDisposition(b.disposition)) {
    sendError(res, 400, 'invalid request');
    return true;
  }
  if (npcExists(b.id)) {
    sendError(res, 409, 'npc already exists');
    return true;
  }
  const faction = getFaction(b.faction_id);
  if (!faction || faction.campaign_id !== campaignId) {
    sendError(res, 400, 'faction not found');
    return true;
  }
  const npc: Npc = {
    id: b.id,
    campaign_id: campaignId,
    name: b.name,
    faction_id: b.faction_id,
    disposition: b.disposition,
  };
  createNpc(npc);
  sendJson(res, 201, {
    id: npc.id,
    name: npc.name,
    faction_id: npc.faction_id,
    disposition: npc.disposition,
  });
  return true;
}

export function handleGetRelationships(pathname: string, res: ServerResponse): boolean {
  const match = pathname.match(/^\/v1\/campaigns\/(.+)\/relationships$/);
  if (!match) return false;
  const campaignId = match[1];
  if (!campaignExists(campaignId)) {
    sendError(res, 404, 'campaign not found');
    return true;
  }
  sendJson(res, 200, {
    campaign_id: campaignId,
    factions: countFactionsByCampaign(campaignId),
    npcs: countNpcsByCampaign(campaignId),
    friendly_npcs: countFriendlyNpcsByCampaign(campaignId),
  });
  return true;
}
