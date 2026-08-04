/**
 * Campaign content records (scenes, lore, etc.) with deterministic tags.
 * Only the DM may create content or replace its tags; any campaign member
 * may list content, with players able to exclude a tag from their results.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

interface ContentRow {
  campaign_id: string;
  sequence: number;
  content_id: string;
  kind: string;
  text: string;
  tags_json: string;
}

interface ContentObject {
  content_id: string;
  kind: string;
  text: string;
  tags: string[];
}

function toContentObject(row: ContentRow): ContentObject {
  return {
    content_id: row.content_id,
    kind: row.kind,
    text: row.text,
    tags: JSON.parse(row.tags_json) as string[],
  };
}

function parseTags(value: unknown, allowEmpty: boolean): string[] | ApiResult {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) {
    return {
      status: 400,
      body: { error: allowEmpty ? 'tags must be an array' : 'tags must be a non-empty array' },
    };
  }
  const seen = new Set<string>();
  for (const entry of value) {
    if (typeof entry !== 'string' || entry.length === 0) {
      return { status: 400, body: { error: 'tags must be non-empty strings' } };
    }
    if (seen.has(entry)) {
      return { status: 400, body: { error: 'tags must be unique' } };
    }
    seen.add(entry);
  }
  return value as string[];
}

export function createContent(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the dm may create content' } };
  }

  const record = body as Record<string, unknown>;
  const contentId = record?.content_id;
  if (typeof contentId !== 'string' || contentId.length === 0) {
    return { status: 400, body: { error: 'content_id must be a non-empty string' } };
  }
  const kind = record?.kind;
  if (typeof kind !== 'string' || kind.length === 0) {
    return { status: 400, body: { error: 'kind must be a non-empty string' } };
  }
  const text = record?.text;
  if (typeof text !== 'string' || text.length === 0) {
    return { status: 400, body: { error: 'text must be a non-empty string' } };
  }
  const tags = parseTags(record?.tags, false);
  if (isApiResult(tags)) return tags;

  const existing = db
    .prepare('SELECT content_id FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?')
    .get(campaignId, contentId);
  if (existing) {
    return { status: 409, body: { error: 'content_id already exists' } };
  }

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_content WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };

  db.prepare(
    'INSERT INTO play_campaign_content (campaign_id, sequence, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequenceRow.max_sequence + 1, contentId, kind, text, JSON.stringify(tags));

  return { status: 201, body: { content_id: contentId, kind, text, tags } as unknown as JsonValue };
}

export function updateContentTags(
  authHeader: string | undefined,
  campaignId: string,
  contentId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the dm may replace content tags' } };
  }

  const row = db
    .prepare('SELECT campaign_id, sequence, content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?')
    .get(campaignId, contentId) as ContentRow | undefined;
  if (!row) {
    return { status: 404, body: { error: 'content not found' } };
  }

  const tags = parseTags((body as Record<string, unknown>)?.tags, true);
  if (isApiResult(tags)) return tags;

  db.prepare('UPDATE play_campaign_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?').run(
    JSON.stringify(tags),
    campaignId,
    contentId,
  );

  return { status: 200, body: toContentObject({ ...row, tags_json: JSON.stringify(tags) }) as unknown as JsonValue };
}

export function listContent(authHeader: string | undefined, campaignId: string, excludeTag: string | undefined): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (excludeTag !== undefined && excludeTag.length === 0) {
    return { status: 400, body: { error: 'exclude_tag must be a non-empty string' } };
  }

  const rows = db
    .prepare(
      'SELECT campaign_id, sequence, content_id, kind, text, tags_json FROM play_campaign_content WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as unknown as ContentRow[];

  const isDm = campaign.owner === actor.username;
  const items = rows
    .map(toContentObject)
    .filter((item) => isDm || !excludeTag || !item.tags.includes(excludeTag));

  return { status: 200, body: { content: items } as unknown as JsonValue };
}
