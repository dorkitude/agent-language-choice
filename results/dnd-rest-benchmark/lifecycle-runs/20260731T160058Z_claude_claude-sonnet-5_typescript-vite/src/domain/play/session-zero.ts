/**
 * Pre-start campaign session-zero settings: rules version, tone, and
 * consent boundaries. Only the DM may set them, and only while the
 * campaign is still in `lobby`; any campaign member may read them back.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface SessionZeroSettings {
  rules: string;
  tone: string;
  consent: string[];
}

function parseSettings(body: JsonValue): SessionZeroSettings | ApiResult {
  const rules = (body as Record<string, unknown>)?.rules;
  if (typeof rules !== 'string' || rules.length === 0) {
    return { status: 400, body: { error: 'rules must be a non-empty string' } };
  }

  const tone = (body as Record<string, unknown>)?.tone;
  if (typeof tone !== 'string' || tone.length === 0) {
    return { status: 400, body: { error: 'tone must be a non-empty string' } };
  }

  const consent = (body as Record<string, unknown>)?.consent;
  if (!Array.isArray(consent) || consent.length === 0) {
    return { status: 400, body: { error: 'consent must be a non-empty array' } };
  }
  const seen = new Set<string>();
  for (const entry of consent) {
    if (typeof entry !== 'string' || entry.length === 0) {
      return { status: 400, body: { error: 'consent entries must be non-empty strings' } };
    }
    if (seen.has(entry)) {
      return { status: 400, body: { error: 'consent entries must be unique' } };
    }
    seen.add(entry);
  }

  return { rules, tone, consent: consent as string[] };
}

export function updateSessionZero(
  authHeader: string | undefined,
  campaignId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the dm may set session-zero settings' } };
  }

  if (campaign.status !== 'lobby') {
    return { status: 409, body: { error: 'session-zero settings can only be changed in the lobby' } };
  }

  const settings = parseSettings(body);
  if (isApiResult(settings)) return settings;

  db.prepare(
    `INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?)
     ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json`,
  ).run(campaignId, settings.rules, settings.tone, JSON.stringify(settings.consent));

  return { status: 200, body: { rules: settings.rules, tone: settings.tone, consent: settings.consent } };
}

export function getSessionZero(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const row = db
    .prepare('SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?')
    .get(campaignId) as { rules: string; tone: string; consent_json: string } | undefined;

  if (!row) {
    return { status: 404, body: { error: 'session-zero settings not set' } };
  }

  return {
    status: 200,
    body: { rules: row.rules, tone: row.tone, consent: JSON.parse(row.consent_json) },
  };
}
