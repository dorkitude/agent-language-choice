/**
 * Character spellbooks within a play campaign: learning and listing known
 * spells, gated by class eligibility. See shared.ts for the ownership model.
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { authenticate, isActor, isApiResult, findCampaign, findMemberByCharacterId, requireParticipant, resolveCharacterOwner } from './shared.ts';

// Classes that can know at least one spell; barbarian, fighter, monk, and
// rogue have no spellcasting at all.
const SPELL_CLASSES: Record<string, string[]> = {
  'fire-bolt': ['wizard', 'sorcerer'],
  'ray-of-frost': ['wizard', 'sorcerer'],
  'mage-hand': ['wizard', 'sorcerer', 'bard', 'warlock'],
  'prestidigitation': ['wizard', 'sorcerer', 'bard', 'warlock'],
  'magic-missile': ['wizard', 'sorcerer'],
  'shield': ['wizard', 'sorcerer'],
  'detect-magic': ['wizard', 'sorcerer', 'bard', 'cleric', 'druid', 'paladin', 'ranger'],
  'sacred-flame': ['cleric'],
  'guidance': ['cleric', 'druid'],
  'cure-wounds': ['cleric', 'druid', 'paladin', 'bard', 'ranger'],
  'healing-word': ['cleric', 'druid', 'bard'],
  'vicious-mockery': ['bard'],
  'eldritch-blast': ['warlock'],
  'hex': ['warlock'],
  'hunters-mark': ['ranger'],
  'thorn-whip': ['druid'],
};

export function addSpell(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may add a spell' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const spellId = body.spell_id;
  if (typeof spellId !== 'string' || spellId.length === 0) {
    return { status: 400, body: { error: 'spell_id must be a non-empty string' } };
  }

  const name = body.name;
  if (typeof name !== 'string' || name.length === 0) {
    return { status: 400, body: { error: 'name must be a non-empty string' } };
  }

  if (!isValidIntInRange(body.level, 0, 9)) {
    return { status: 400, body: { error: 'level must be an integer from 0 through 9' } };
  }
  const level = body.level as number;

  const eligibleClasses = SPELL_CLASSES[spellId];
  if (!eligibleClasses || !eligibleClasses.includes(member.class)) {
    return { status: 400, body: { error: `${spellId} is not a valid spell for class ${member.class}` } };
  }

  const existing = db
    .prepare('SELECT 1 FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?')
    .get(campaignId, characterId, spellId);
  if (existing) {
    return { status: 409, body: { error: 'character already knows this spell' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, characterId, spellId, name, level);

  return { status: 201, body: { spell_id: spellId, name, level } };
}

// A character's class can prepare spells only if it appears as an eligible
// class for at least one spell in SPELL_CLASSES.
const SPELLCASTING_CLASSES = new Set(Object.values(SPELL_CLASSES).flat());

// Simplified maximum-prepared-spells rule: one prepared spell per character
// level, matching the level-1 wizard example in the spec (max 1).
function maxPreparedSpells(memberClass: string, level: number): number {
  return SPELLCASTING_CLASSES.has(memberClass) ? level : 0;
}

export function setPreparedSpells(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may prepare spells' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  if (!SPELLCASTING_CLASSES.has(member.class)) {
    return { status: 400, body: { error: `${member.class} is not a spellcasting class` } };
  }

  const spellIds = body.spell_ids;
  if (!Array.isArray(spellIds) || !spellIds.every((id) => typeof id === 'string' && id.length > 0)) {
    return { status: 400, body: { error: 'spell_ids must be an array of strings' } };
  }

  const maxPrepared = maxPreparedSpells(member.class, member.level);
  if (spellIds.length > maxPrepared) {
    return { status: 400, body: { error: `prepared spells cannot exceed ${maxPrepared} for this level` } };
  }

  const knownRows = db
    .prepare('SELECT spell_id FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ?')
    .all(campaignId, characterId) as { spell_id: string }[];
  const known = new Set(knownRows.map((row) => row.spell_id));
  for (const spellId of spellIds as string[]) {
    if (!known.has(spellId)) {
      return { status: 400, body: { error: `${spellId} is not a known spell` } };
    }
  }

  db.prepare('DELETE FROM play_campaign_prepared_spells WHERE campaign_id = ? AND character_id = ?').run(
    campaignId,
    characterId,
  );
  const insert = db.prepare(
    'INSERT INTO play_campaign_prepared_spells (campaign_id, character_id, spell_id) VALUES (?, ?, ?)',
  );
  for (const spellId of spellIds as string[]) {
    insert.run(campaignId, characterId, spellId);
  }

  return {
    status: 200,
    body: { character_id: characterId, prepared_spells: spellIds as string[], max_prepared: maxPrepared },
  };
}

export function getPreparedSpells(authHeader: string | undefined, campaignId: string, characterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const rows = db
    .prepare(
      'SELECT spell_id FROM play_campaign_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC',
    )
    .all(campaignId, characterId) as { spell_id: string }[];

  return {
    status: 200,
    body: {
      character_id: characterId,
      prepared_spells: rows.map((row) => row.spell_id),
      max_prepared: maxPreparedSpells(member.class, member.level),
    },
  };
}

// Full-caster spell slot progression by character level, matching the
// level-1-wizard example in the spec (one 1st-level slot). Every class in
// SPELLCASTING_CLASSES follows this same simplified table.
const SPELL_SLOTS_BY_LEVEL: Record<number, Record<number, number>> = {
  1: { 1: 1 },
  2: { 1: 3 },
  3: { 1: 4, 2: 2 },
  4: { 1: 4, 2: 3 },
  5: { 1: 4, 2: 3, 3: 2 },
  6: { 1: 4, 2: 3, 3: 3 },
  7: { 1: 4, 2: 3, 3: 3, 4: 1 },
  8: { 1: 4, 2: 3, 3: 3, 4: 2 },
  9: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 1 },
  10: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2 },
  11: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1 },
  12: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1 },
  13: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1 },
  14: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1 },
  15: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1 },
  16: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1 },
  17: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1 },
  18: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1 },
  19: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1 },
  20: { 1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1 },
};

function spellSlotsForLevel(memberClass: string, level: number): Record<number, number> {
  if (!SPELLCASTING_CLASSES.has(memberClass)) return {};
  const clamped = Math.min(20, Math.max(1, level));
  return SPELL_SLOTS_BY_LEVEL[clamped];
}

export function castSpell(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may cast a spell' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const spellId = body.spell_id;
  if (typeof spellId !== 'string' || spellId.length === 0) {
    return { status: 400, body: { error: 'spell_id must be a non-empty string' } };
  }

  const target = body.target;
  if (typeof target !== 'string' || target.length === 0) {
    return { status: 400, body: { error: 'target must be a non-empty string' } };
  }

  if (!SPELLCASTING_CLASSES.has(member.class)) {
    return { status: 400, body: { error: `${member.class} is not a spellcasting class` } };
  }

  const preparedRow = db
    .prepare('SELECT 1 FROM play_campaign_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?')
    .get(campaignId, characterId, spellId);
  if (!preparedRow) {
    return { status: 400, body: { error: `${spellId} is not currently prepared` } };
  }

  const spellRow = db
    .prepare('SELECT level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?')
    .get(campaignId, characterId, spellId) as { level: number } | undefined;
  if (!spellRow) {
    return { status: 400, body: { error: `${spellId} is not currently prepared` } };
  }
  const slotLevel = spellRow.level;

  const slots = spellSlotsForLevel(member.class, member.level);
  const total = slots[slotLevel] ?? 0;

  const usedRow = db
    .prepare(
      'SELECT COUNT(*) AS count FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?',
    )
    .get(campaignId, characterId, slotLevel) as { count: number };
  const used = usedRow.count;
  if (used >= total) {
    return { status: 409, body: { error: 'no remaining spell slots of the required level' } };
  }
  const slotsRemaining = total - used - 1;

  const sequenceRow = db
    .prepare('SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ?')
    .get(campaignId, characterId) as { max_sequence: number };
  const sequence = sequenceRow.max_sequence + 1;

  db.prepare(
    'INSERT INTO play_campaign_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)',
  ).run(campaignId, characterId, sequence, spellId, target, slotLevel, slotsRemaining);

  return {
    status: 201,
    body: {
      character_id: characterId,
      spell_id: spellId,
      target,
      slot_level: slotLevel,
      slots_remaining: slotsRemaining,
      sequence,
    },
  };
}

export function listCasts(authHeader: string | undefined, campaignId: string, characterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const rows = db
    .prepare(
      'SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC',
    )
    .all(campaignId, characterId) as {
    spell_id: string;
    target: string;
    slot_level: number;
    slots_remaining: number;
    sequence: number;
  }[];

  return {
    status: 200,
    body: {
      casts: rows.map((row) => ({
        character_id: characterId,
        spell_id: row.spell_id,
        target: row.target,
        slot_level: row.slot_level,
        slots_remaining: row.slots_remaining,
        sequence: row.sequence,
      })),
    },
  };
}

type ConcentrationRow = { spell_id: string; target: string; remaining_turns: number };

function concentrationBody(characterId: string, row: ConcentrationRow | undefined): JsonValue {
  return {
    character_id: characterId,
    concentration: row
      ? { spell_id: row.spell_id, target: row.target, remaining_turns: row.remaining_turns }
      : null,
  };
}

export function setConcentration(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may set concentration' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const spellId = body.spell_id;
  if (typeof spellId !== 'string' || spellId.length === 0) {
    return { status: 400, body: { error: 'spell_id must be a non-empty string' } };
  }

  const target = body.target;
  if (typeof target !== 'string' || target.length === 0) {
    return { status: 400, body: { error: 'target must be a non-empty string' } };
  }

  if (!isValidIntInRange(body.duration_turns, 1, Number.MAX_SAFE_INTEGER)) {
    return { status: 400, body: { error: 'duration_turns must be a positive integer' } };
  }
  const durationTurns = body.duration_turns as number;

  if (!SPELLCASTING_CLASSES.has(member.class)) {
    return { status: 400, body: { error: `${member.class} is not a spellcasting class` } };
  }

  const knownRow = db
    .prepare('SELECT 1 FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?')
    .get(campaignId, characterId, spellId);
  if (!knownRow) {
    return { status: 400, body: { error: `${spellId} is not a known spell` } };
  }

  const preparedRow = db
    .prepare('SELECT 1 FROM play_campaign_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?')
    .get(campaignId, characterId, spellId);
  if (!preparedRow) {
    return { status: 400, body: { error: `${spellId} is not currently prepared` } };
  }

  db.prepare('DELETE FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?').run(
    campaignId,
    characterId,
  );
  db.prepare(
    'INSERT INTO play_campaign_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?)',
  ).run(campaignId, characterId, spellId, target, durationTurns);

  return {
    status: 200,
    body: concentrationBody(characterId, { spell_id: spellId, target, remaining_turns: durationTurns }),
  };
}

export function getConcentration(authHeader: string | undefined, campaignId: string, characterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const row = db
    .prepare(
      'SELECT spell_id, target, remaining_turns FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?',
    )
    .get(campaignId, characterId) as ConcentrationRow | undefined;

  return { status: 200, body: concentrationBody(characterId, row) };
}

export function advanceConcentrationTurn(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const row = db
    .prepare(
      'SELECT spell_id, target, remaining_turns FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?',
    )
    .get(campaignId, characterId) as ConcentrationRow | undefined;

  if (!row) {
    return { status: 200, body: concentrationBody(characterId, undefined) };
  }

  const remaining = row.remaining_turns - 1;
  if (remaining <= 0) {
    db.prepare('DELETE FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?').run(
      campaignId,
      characterId,
    );
    return { status: 200, body: concentrationBody(characterId, undefined) };
  }

  db.prepare(
    'UPDATE play_campaign_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?',
  ).run(remaining, campaignId, characterId);

  return {
    status: 200,
    body: concentrationBody(characterId, { spell_id: row.spell_id, target: row.target, remaining_turns: remaining }),
  };
}

export function clearConcentration(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }
  if (owner !== actor.username) {
    return { status: 403, body: { error: 'only the character owner may clear concentration' } };
  }

  db.prepare('DELETE FROM play_campaign_concentration WHERE campaign_id = ? AND character_id = ?').run(
    campaignId,
    characterId,
  );

  return { status: 200, body: concentrationBody(characterId, undefined) };
}

export function listSpells(authHeader: string | undefined, campaignId: string, characterId: string): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (!owner) {
    return { status: 404, body: { error: 'character not found' } };
  }

  const rows = db
    .prepare('SELECT spell_id, name, level FROM play_campaign_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC')
    .all(campaignId, characterId) as { spell_id: string; name: string; level: number }[];

  return { status: 200, body: { spells: rows } };
}
