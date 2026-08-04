/**
 * DM-only campaign backups: immutable, sequentially numbered snapshots of a
 * campaign's current public `story` and `status`. Only the campaign DM may
 * create, list, or restore backups; members (and everyone else) are
 * forbidden. Restoring an existing snapshot applies it to the campaign
 * without mutating the snapshot or creating a new one.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

interface BackupRow {
  backup_id: string;
  story: string;
  status: string;
}

function nextBackupId(db: ReturnType<typeof getDb>, campaignId: string): { sequence: number; backupId: string } {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_backups WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  const sequence = row.max_sequence + 1;
  return { sequence, backupId: `backup-${sequence}` };
}

function toBackupBody(row: BackupRow): JsonValue {
  return { backup_id: row.backup_id, story: row.story, status: row.status } as unknown as JsonValue;
}

export function createCampaignBackup(authHeader: string | undefined, campaignId: string, _body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may create backups' } };
  }

  const { sequence, backupId } = nextBackupId(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_backups (campaign_id, sequence, backup_id, story, status) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, backupId, campaign.story, campaign.status);

  return { status: 201, body: toBackupBody({ backup_id: backupId, story: campaign.story, status: campaign.status }) };
}

export function listCampaignBackups(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may list backups' } };
  }

  const rows = db
    .prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC')
    .all(campaignId) as unknown as BackupRow[];

  return { status: 200, body: { backups: rows.map(toBackupBody) } as unknown as JsonValue };
}

export function restoreCampaignBackup(
  authHeader: string | undefined,
  campaignId: string,
  backupId: string,
  _body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may restore backups' } };
  }

  const row = db
    .prepare('SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = ? AND backup_id = ?')
    .get(campaignId, backupId) as BackupRow | undefined;

  if (!row) {
    return { status: 404, body: { error: 'backup not found' } };
  }

  db.prepare('UPDATE play_campaigns SET story = ?, status = ? WHERE id = ?').run(row.story, row.status, campaignId);

  return { status: 200, body: toBackupBody(row) };
}
