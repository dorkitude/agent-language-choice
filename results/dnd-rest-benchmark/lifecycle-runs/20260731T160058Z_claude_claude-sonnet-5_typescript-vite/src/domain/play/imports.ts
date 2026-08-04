/**
 * DM-only campaign imports: accept a compatible version 1 snapshot (story +
 * status) and apply it atomically to the campaign. Only the campaign DM may
 * create or read imports; members (and everyone else) are forbidden.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

const VALID_STATUSES = new Set(['lobby', 'started']);

interface ImportRow {
  version: number;
  story: string;
  status: string;
}

function toImportBody(row: ImportRow): JsonValue {
  return { version: row.version, story: row.story, status: row.status } as unknown as JsonValue;
}

function validateSnapshot(body: JsonValue): ImportRow | ApiResult {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { status: 400, body: { error: 'import body must be an object' } };
  }
  const snapshot = body as Record<string, unknown>;
  if (snapshot.version !== 1) {
    return { status: 400, body: { error: 'version must be 1' } };
  }
  if (typeof snapshot.story !== 'string' || snapshot.story.length === 0) {
    return { status: 400, body: { error: 'story must be a non-empty string' } };
  }
  if (typeof snapshot.status !== 'string' || !VALID_STATUSES.has(snapshot.status)) {
    return { status: 400, body: { error: 'status must be lobby or started' } };
  }
  return { version: 1, story: snapshot.story, status: snapshot.status };
}

export function importCampaignSnapshot(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may create imports' } };
  }

  const snapshot = validateSnapshot(body);
  if (isApiResult(snapshot)) return snapshot;

  db.prepare('UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?').run(
    snapshot.story,
    snapshot.status,
    campaignId,
  );
  db.prepare(
    'INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ' +
      'ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status',
  ).run(campaignId, snapshot.version, snapshot.story, snapshot.status);

  return { status: 200, body: toImportBody(snapshot) };
}

export function getCampaignImportState(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may read imported state' } };
  }

  const row = db
    .prepare('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?')
    .get(campaignId) as ImportRow | undefined;

  if (!row) {
    return { status: 404, body: { error: 'no import found' } };
  }

  return { status: 200, body: toImportBody(row) };
}
