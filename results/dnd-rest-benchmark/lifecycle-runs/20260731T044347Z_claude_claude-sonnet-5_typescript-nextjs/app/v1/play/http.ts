import { PlayCampaign, PlayEvent, getPlayCampaign, listRecentPlayEvents } from "./store.js";

// Every play-campaign-scoped route needs the same "does this play campaign
// exist" check before doing anything else. Returns the campaign on success,
// or the 404 Response every caller returned by hand before this was extracted.
export function requirePlayCampaign(campaignId: string): PlayCampaign | Response {
  const campaign = getPlayCampaign(campaignId);
  if (campaign) return campaign;
  return Response.json({ error: `play campaign ${campaignId} not found` }, { status: 404 });
}

/**
 * Several DM-only actions (editing the campaign document, narrating, sending
 * a turn nudge, starting the campaign) share the same "must be the owning
 * dm" gate, but each historically had its own copy of the check with its own
 * error wording. Callers still supply their own message; only the comparison
 * and the 403 shape are shared. Returns null when the check passes.
 */
export function requireCampaignOwner(
  campaign: PlayCampaign,
  username: string,
  errorMessage: string,
): Response | null {
  if (username === campaign.owner) return null;
  return Response.json({ error: errorMessage }, { status: 403 });
}

// The gm-status and my-turn views both render the same trailing slice of
// event history, trimmed to the fields a party member/DM needs (no `type`,
// which is only relevant to the `/actions` endpoint that produced it).
export const RECENT_EVENTS_LIMIT = 10;

export interface PlayEventSummary {
  sequence: number;
  kind: string;
  actor: string;
  text: string;
}

function summarizePlayEvent(event: PlayEvent): PlayEventSummary {
  return { sequence: event.sequence, kind: event.kind, actor: event.actor, text: event.text };
}

export function listRecentPlayEventSummaries(
  campaignId: string,
  limit: number = RECENT_EVENTS_LIMIT,
): PlayEventSummary[] {
  return listRecentPlayEvents(campaignId, limit).map(summarizePlayEvent);
}
