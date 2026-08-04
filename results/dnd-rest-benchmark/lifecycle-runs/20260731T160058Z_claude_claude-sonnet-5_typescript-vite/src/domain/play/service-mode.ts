/**
 * Process-global maintenance switch consulted by the public readiness
 * endpoint. Only a DM may toggle it, and it is not campaign-scoped.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

let maintenanceMode = false;

export function isInMaintenance(): boolean {
  return maintenanceMode;
}

export function setServiceMode(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.role !== 'dm') {
    return { status: 403, body: { error: 'only a dm may change service mode' } };
  }

  const maintenance = body.maintenance;
  if (typeof maintenance !== 'boolean') {
    return { status: 400, body: { error: 'maintenance must be a boolean' } };
  }

  maintenanceMode = maintenance;
  return { status: 200, body: { maintenance: maintenanceMode } };
}
