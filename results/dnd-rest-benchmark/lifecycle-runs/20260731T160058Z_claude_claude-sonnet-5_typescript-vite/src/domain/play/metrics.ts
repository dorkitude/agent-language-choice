/**
 * Campaign-scoped service metrics. Exposes only safe aggregate counters
 * (never story, character, event, or actor content) to the campaign owner.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

interface MetricsRow {
  accepted_rate_events: number;
  rejected_rate_events: number;
  projection_events: number;
}

export function getServiceMetrics(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign owner may read service metrics' } };
  }

  const row = db
    .prepare(
      'SELECT accepted_rate_events, rejected_rate_events, projection_events FROM play_campaign_metrics WHERE campaign_id = ?',
    )
    .get(campaignId) as MetricsRow | undefined;

  return {
    status: 200,
    body: {
      accepted_rate_events: row?.accepted_rate_events ?? 0,
      rejected_rate_events: row?.rejected_rate_events ?? 0,
      projection_events: row?.projection_events ?? 0,
      uptime_ticks: 1,
    } as unknown as JsonValue,
  };
}
