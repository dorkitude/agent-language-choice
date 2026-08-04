import { IncomingMessage, ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import {
  createLocation,
  createLocationConnection,
  getPlayCampaign,
  getPlayMembershipByCampaignAndUser,
  locationConnectionExists,
  locationExists,
  getLocationConnections,
  updatePlayCampaignCurrentLocation,
} from '../repository.js';
import { requireActor } from '../play-auth.js';
import { isNonEmptyString, isPositiveInteger } from '../validators.js';
import type { Location, LocationConnection } from '../types.js';

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

export function handleCreateLocation(
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

  if (locationExists(id, params.id)) {
    sendJSON(res, 409, { error: 'location already exists' });
    return;
  }

  const location: Location = {
    id,
    campaign_id: params.id,
    name,
  };
  createLocation(location);
  if (!campaign.current_location_id) {
    updatePlayCampaignCurrentLocation(params.id, location.id);
  }
  sendJSON(res, 201, { id: location.id, name: location.name });
}

export function handleCreateLocationConnection(
  res: ServerResponse,
  params: Record<string, string>,
  body: unknown,
  req: IncomingMessage,
): void {
  const campaign = getPlayCampaignOr404(res, params.id);
  if (!campaign) return;

  const actor = requireOwner(req, res, campaign);
  if (!actor) return;

  const { to_id, travel_turns } = body as Record<string, unknown>;
  if (!isNonEmptyString(to_id) || !isPositiveInteger(travel_turns)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (!locationExists(params.from_id, params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }
  if (!locationExists(to_id, params.id)) {
    sendJSON(res, 400, { error: 'destination location does not exist' });
    return;
  }
  if (locationConnectionExists(params.from_id, to_id, params.id)) {
    sendJSON(res, 400, { error: 'connection already exists' });
    return;
  }

  const connection: LocationConnection = {
    from_id: params.from_id,
    to_id,
    campaign_id: params.id,
    travel_turns,
  };
  createLocationConnection(connection);
  sendJSON(res, 201, {
    from_id: connection.from_id,
    to_id: connection.to_id,
    travel_turns: connection.travel_turns,
  });
}

export function handleGetTravel(
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

  if (!locationExists(params.loc_id, params.id)) {
    sendJSON(res, 404, { error: 'not found' });
    return;
  }

  const connections = getLocationConnections(params.loc_id, params.id);
  sendJSON(res, 200, {
    destinations: connections.map((c) => ({
      id: c.to_id,
      name: c.name,
      travel_turns: c.travel_turns,
    })),
  });
}
