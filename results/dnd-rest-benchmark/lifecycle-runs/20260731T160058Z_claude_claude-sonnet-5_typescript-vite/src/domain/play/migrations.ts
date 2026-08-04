/**
 * DM-only campaign schema migrations: accept a legacy schema version 1
 * snapshot (story only) and deterministically migrate it to schema version
 * 2, stamping in the campaign's current name. Only the campaign DM may
 * create or read migrations; everyone else is forbidden.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign } from './shared.ts';

interface MigratedState {
  schema_version: 2;
  story: string;
  campaign_name: string;
}

interface MigrationRow {
  input_story: string;
  story: string;
  campaign_name: string;
}

function toMigratedBody(row: { story: string; campaign_name: string }): JsonValue {
  return { schema_version: 2, story: row.story, campaign_name: row.campaign_name } as unknown as JsonValue;
}

function validateSnapshot(body: JsonValue): { story: string } | ApiResult {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { status: 400, body: { error: 'migration body must be an object' } };
  }
  const snapshot = body as Record<string, unknown>;
  if (snapshot.schema_version !== 1) {
    return { status: 400, body: { error: 'schema_version must be 1' } };
  }
  if (typeof snapshot.story !== 'string' || snapshot.story.length === 0) {
    return { status: 400, body: { error: 'story must be a non-empty string' } };
  }
  return { story: snapshot.story };
}

export function migrateCampaignSnapshot(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may create migrations' } };
  }

  const snapshot = validateSnapshot(body);
  if (isApiResult(snapshot)) return snapshot;

  const existing = db
    .prepare('SELECT input_story, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?')
    .get(campaignId) as MigrationRow | undefined;

  if (existing && existing.input_story === snapshot.story) {
    return { status: 200, body: toMigratedBody(existing) };
  }

  const migrated: MigratedState = { schema_version: 2, story: snapshot.story, campaign_name: campaign.name };

  db.prepare(
    'INSERT INTO play_campaign_migrations (campaign_id, input_story, story, campaign_name) VALUES (?, ?, ?, ?) ' +
      'ON CONFLICT(campaign_id) DO UPDATE SET input_story = excluded.input_story, story = excluded.story, campaign_name = excluded.campaign_name',
  ).run(campaignId, snapshot.story, migrated.story, migrated.campaign_name);

  return { status: 201, body: toMigratedBody(migrated) };
}

export function getCampaignMigrationState(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign DM may read migrated state' } };
  }

  const row = db
    .prepare('SELECT input_story, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?')
    .get(campaignId) as MigrationRow | undefined;

  if (!row) {
    return { status: 404, body: { error: 'no migration found' } };
  }

  return { status: 200, body: toMigratedBody(row) };
}
