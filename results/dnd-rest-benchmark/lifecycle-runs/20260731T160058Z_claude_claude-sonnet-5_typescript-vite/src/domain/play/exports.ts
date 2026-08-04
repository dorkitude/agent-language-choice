/**
 * DM-only campaign exports: immutable, sequentially versioned snapshots of a
 * campaign's current public `story` and `status`. Only the campaign DM may
 * create or read exports; members (and everyone else) are forbidden.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

interface ExportRow {
  version: number;
  story: string;
  status: string;
}

function nextVersion(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COUNT(*) AS count FROM play_campaign_exports WHERE campaign_id = ?')
    .get(campaignId) as { count: number };
  return row.count + 1;
}

function toExportBody(row: ExportRow): JsonValue {
  return { version: row.version, story: row.story, status: row.status } as unknown as JsonValue;
}

export function createCampaignExport(authHeader: string | undefined, campaignId: string, _body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may create exports' } };
  }

  const version = nextVersion(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)',
  ).run(campaignId, version, campaign.story, campaign.status);

  return { status: 201, body: toExportBody({ version, story: campaign.story, status: campaign.status }) };
}

export function listCampaignExports(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may list exports' } };
  }

  const rows = db
    .prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC')
    .all(campaignId) as unknown as ExportRow[];

  return { status: 200, body: { exports: rows.map(toExportBody) } as unknown as JsonValue };
}

export function getCampaignExport(authHeader: string | undefined, campaignId: string, versionParam: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may read exports' } };
  }

  const version = Number(versionParam);
  if (!Number.isInteger(version)) {
    return { status: 404, body: { error: 'export not found' } };
  }

  const row = db
    .prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?')
    .get(campaignId, version) as ExportRow | undefined;

  if (!row) {
    return { status: 404, body: { error: 'export not found' } };
  }

  return { status: 200, body: toExportBody(row) };
}
