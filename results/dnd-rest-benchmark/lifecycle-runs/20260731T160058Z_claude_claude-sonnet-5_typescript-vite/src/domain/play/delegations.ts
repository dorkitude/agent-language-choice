/**
 * Campaign-scoped GM delegation: the campaign owner grants and revokes
 * limited co-GM powers (currently only `narrate`) to an existing campaign
 * member.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { authenticate, isActor, isApiResult, findCampaign, isMember } from './shared.ts';

const VALID_POWERS = new Set(['narrate']);

interface DelegationRow {
  campaign_id: string;
  username: string;
  powers_json: string;
  active: number;
}

function toDelegationBody(row: { username: string; powers_json: string; active: number }): JsonValue {
  return {
    username: row.username,
    powers: JSON.parse(row.powers_json),
    active: row.active === 1,
  } as unknown as JsonValue;
}

export function hasActivePower(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  username: string,
  power: string,
): boolean {
  const row = db
    .prepare('SELECT powers_json FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1')
    .get(campaignId, username) as { powers_json: string } | undefined;
  if (!row) return false;
  const powers = JSON.parse(row.powers_json) as string[];
  return powers.includes(power);
}

function nextAuditSequence(db: ReturnType<typeof getDb>, campaignId: string): number {
  const row = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_delegation_audit WHERE campaign_id = ?')
    .get(campaignId) as { max_sequence: number };
  return row.max_sequence + 1;
}

function insertAuditEntry(
  db: ReturnType<typeof getDb>,
  campaignId: string,
  username: string,
  action: 'granted' | 'revoked',
  powers: string[],
): void {
  const sequence = nextAuditSequence(db, campaignId);
  db.prepare(
    'INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, sequence, username, action, JSON.stringify(powers));
}

export function grantDelegation(authHeader: string | undefined, campaignId: string, body: JsonValue): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign owner may grant delegation' } };
  }

  const username = body.username;
  if (typeof username !== 'string' || username.length === 0) {
    return { status: 400, body: { error: 'username must be a non-empty string' } };
  }

  const powers = body.powers;
  if (!Array.isArray(powers) || powers.length === 0) {
    return { status: 400, body: { error: 'powers must be a nonempty array' } };
  }
  const uniquePowers = new Set(powers);
  if (uniquePowers.size !== powers.length) {
    return { status: 400, body: { error: 'powers must not contain duplicates' } };
  }
  for (const power of powers) {
    if (typeof power !== 'string' || !VALID_POWERS.has(power)) {
      return { status: 400, body: { error: `invalid power: ${String(power)}` } };
    }
  }

  if (!isMember(db, campaignId, username)) {
    return { status: 400, body: { error: 'username must be a campaign member' } };
  }

  const existing = db
    .prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?')
    .get(campaignId, username) as { active: number } | undefined;
  if (existing && existing.active === 1) {
    return { status: 409, body: { error: 'an active delegation already exists for this user' } };
  }

  const powersList = powers as string[];
  db.prepare(
    'INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1) ' +
      'ON CONFLICT(campaign_id, username) DO UPDATE SET powers_json = excluded.powers_json, active = 1',
  ).run(campaignId, username, JSON.stringify(powersList));

  insertAuditEntry(db, campaignId, username, 'granted', powersList);

  return {
    status: 201,
    body: toDelegationBody({ username, powers_json: JSON.stringify(powersList), active: 1 }),
  };
}

export function revokeDelegation(
  authHeader: string | undefined,
  campaignId: string,
  username: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign owner may revoke delegation' } };
  }

  const row = db
    .prepare('SELECT campaign_id, username, powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?')
    .get(campaignId, username) as DelegationRow | undefined;
  if (!row || row.active !== 1) {
    return { status: 404, body: { error: 'active delegation not found' } };
  }

  db.prepare('UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?').run(
    campaignId,
    username,
  );

  const powers = JSON.parse(row.powers_json) as string[];
  insertAuditEntry(db, campaignId, username, 'revoked', powers);

  return {
    status: 200,
    body: toDelegationBody({ username, powers_json: row.powers_json, active: 0 }),
  };
}

export function getDelegationAudit(authHeader: string | undefined, campaignId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the campaign owner may read delegation audit' } };
  }

  const rows = db
    .prepare(
      'SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId) as { username: string; action: string; powers_json: string }[];

  return {
    status: 200,
    body: {
      entries: rows.map((row) => ({
        username: row.username,
        action: row.action,
        powers: JSON.parse(row.powers_json),
      })),
    } as unknown as JsonValue,
  };
}
