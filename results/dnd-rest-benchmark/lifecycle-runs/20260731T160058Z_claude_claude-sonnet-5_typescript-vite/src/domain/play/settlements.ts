/**
 * DM-managed campaign settlements with validated services, availability, and
 * player discovery. See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, requireParticipant } from './shared.ts';

const AVAILABILITY_VALUES = new Set(['open', 'limited', 'closed']);

export type SettlementRow = {
  settlement_id: string;
  name: string;
  services_json: string;
  availability: string;
};

function settlementBody(row: SettlementRow, discoveredBy: string[]): JsonValue {
  return {
    settlement_id: row.settlement_id,
    name: row.name,
    services: JSON.parse(row.services_json),
    availability: row.availability,
    discovered_by: discoveredBy,
  } as JsonValue;
}

function parseSettlementFields(body: JsonValue): { name: string; services: string[]; availability: string } | ApiResult {
  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  const servicesRaw = body.services;
  if (!Array.isArray(servicesRaw) || servicesRaw.length === 0) {
    return { status: 400, body: { error: 'services must be a non-empty array of strings' } };
  }
  const services: string[] = [];
  const seen = new Set<string>();
  for (const entry of servicesRaw) {
    if (typeof entry !== 'string') {
      return { status: 400, body: { error: 'services must contain only strings' } };
    }
    const trimmed = entry.trim();
    if (trimmed.length === 0) {
      return { status: 400, body: { error: 'services must contain only non-empty strings' } };
    }
    if (seen.has(trimmed)) {
      return { status: 400, body: { error: 'services must be unique' } };
    }
    seen.add(trimmed);
    services.push(trimmed);
  }

  const availability = body.availability;
  if (typeof availability !== 'string' || !AVAILABILITY_VALUES.has(availability)) {
    return { status: 400, body: { error: "availability must be exactly 'open', 'limited', or 'closed'" } };
  }

  return { name, services, availability };
}

function discoverersFor(db: ReturnType<typeof getDb>, campaignId: string, settlementId: string): string[] {
  const rows = db
    .prepare(
      'SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId, settlementId) as { character_id: string }[];
  return rows.map((row) => row.character_id);
}

export function findSettlement(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  settlementId: string,
): SettlementRow | ApiResult {
  const row = db
    .prepare(
      'SELECT settlement_id, name, services_json, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?',
    )
    .get(campaignId, settlementId) as SettlementRow | undefined;
  return row ?? { status: 404, body: { error: 'settlement not found' } };
}

function nextSettlementSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_settlements WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function nextDiscoverySequence(db: ReturnType<typeof getDb>, campaignId: string, settlementId: string): number {
  const row = db
    .prepare(
      'SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ?',
    )
    .get(campaignId, settlementId) as { max_sequence: number };
  return row.max_sequence + 1;
}

export function createSettlement(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may create settlements' } };
  }

  const settlementId = body.settlement_id;
  if (typeof settlementId !== 'string' || settlementId.length === 0) {
    return { status: 400, body: { error: 'settlement_id must be a non-empty string' } };
  }

  const parsed = parseSettlementFields(body);
  if (isApiResult(parsed)) return parsed;

  const existing = db
    .prepare('SELECT settlement_id FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?')
    .get(campaignId, settlementId);
  if (existing) {
    return { status: 409, body: { error: 'settlement_id already exists in this campaign' } };
  }

  const sequence = nextSettlementSequence(db, campaignId);
  const servicesJson = JSON.stringify(parsed.services);
  db.prepare(
    'INSERT INTO play_campaign_settlements (campaign_id, sequence, settlement_id, name, services_json, availability) VALUES (?, ?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, settlementId, parsed.name, servicesJson, parsed.availability);

  return {
    status: 201,
    body: settlementBody(
      { settlement_id: settlementId, name: parsed.name, services_json: servicesJson, availability: parsed.availability },
      [],
    ),
  };
}

export function updateSettlement(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (campaign.owner !== actor.username) {
    return { status: 403, body: { error: 'only the campaign dm may update settlements' } };
  }

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const parsed = parseSettlementFields(body);
  if (isApiResult(parsed)) return parsed;

  const servicesJson = JSON.stringify(parsed.services);
  db.prepare(
    'UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?',
  ).run(parsed.name, servicesJson, parsed.availability, campaignId, settlementId);

  const discoveredBy = discoverersFor(db, campaignId, settlementId);
  return {
    status: 200,
    body: settlementBody(
      { settlement_id: settlementId, name: parsed.name, services_json: servicesJson, availability: parsed.availability },
      discoveredBy,
    ),
  };
}

export function discoverSettlement(
  authHeader: string | undefined,
  campaignId: string,
  settlementId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  if (campaign.owner === actor.username) {
    return { status: 403, body: { error: 'only joined campaign players may discover settlements' } };
  }

  const settlement = findSettlement(db, campaignId, settlementId);
  if (isApiResult(settlement)) return settlement;

  const memberRow = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, actor.username) as { character_id: string } | undefined;
  if (!memberRow) {
    return { status: 403, body: { error: 'only joined campaign players may discover settlements' } };
  }
  const characterId = memberRow.character_id;

  const existing = db
    .prepare(
      'SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?',
    )
    .get(campaignId, settlementId, characterId);

  if (!existing) {
    const sequence = nextDiscoverySequence(db, campaignId, settlementId);
    db.prepare(
      'INSERT INTO play_campaign_settlement_discoveries (campaign_id, sequence, settlement_id, character_id) VALUES (?, ?, ?, ?)',
    ).run(campaignId, sequence, settlementId, characterId);
  }

  return {
    status: existing ? 200 : 201,
    body: settlementBody(settlement, [characterId]),
  };
}

export function listSettlements(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const rows = db
    .prepare(
      'SELECT settlement_id, name, services_json, availability FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as SettlementRow[];

  if (actor.username === campaign.owner) {
    return {
      status: 200,
      body: { settlements: rows.map((row) => settlementBody(row, discoverersFor(db, campaignId, row.settlement_id))) },
    };
  }

  const memberRow = db
    .prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?')
    .get(campaignId, actor.username) as { character_id: string } | undefined;
  const ownCharacterId = memberRow ? memberRow.character_id : null;

  const visible: JsonValue[] = [];
  for (const row of rows) {
    if (ownCharacterId === null) continue;
    const discoveredBy = discoverersFor(db, campaignId, row.settlement_id);
    if (discoveredBy.includes(ownCharacterId)) {
      visible.push(settlementBody(row, [ownCharacterId]));
    }
  }

  return { status: 200, body: { settlements: visible } };
}
