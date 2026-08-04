import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  campaignExists,
  createFaction,
  createNPC,
  factionExists,
  getRelationshipSummary,
  npcExists,
} from '../repository.js';
import { isNonEmptyString, isValidDisposition, isValidFactionStance } from '../validators.js';
import type { Faction, NPC } from '../types.js';

export function handleCreateFaction(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, name, stance } = body as Record<string, unknown>;
  if (!isNonEmptyString(id) || !isNonEmptyString(name) || !isValidFactionStance(stance)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (factionExists(id)) {
    sendJSON(res, 409, { error: 'faction already exists' });
    return;
  }

  const faction: Faction = { id, campaign_id: params.id, name, stance };
  createFaction(faction);
  sendJSON(res, 201, { id: faction.id, name: faction.name, stance: faction.stance });
}

export function handleCreateNPC(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const { id, name, faction_id, disposition } = body as Record<string, unknown>;
  if (
    !isNonEmptyString(id) ||
    !isNonEmptyString(name) ||
    (faction_id !== undefined && !isNonEmptyString(faction_id)) ||
    !isValidDisposition(disposition)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  if (npcExists(id)) {
    sendJSON(res, 409, { error: 'npc already exists' });
    return;
  }

  const npc: NPC = {
    id,
    campaign_id: params.id,
    name,
    faction_id: faction_id ?? undefined,
    disposition,
  };
  createNPC(npc);
  sendJSON(res, 201, {
    id: npc.id,
    name: npc.name,
    faction_id: npc.faction_id,
    disposition: npc.disposition,
  });
}

export function handleRelationshipSummary(res: ServerResponse, params: Record<string, string>): void {
  if (!campaignExists(params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  sendJSON(res, 200, getRelationshipSummary(params.id));
}
