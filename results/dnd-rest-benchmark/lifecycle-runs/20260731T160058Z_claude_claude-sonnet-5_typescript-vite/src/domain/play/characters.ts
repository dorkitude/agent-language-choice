/**
 * Character HP/death, ownership, build, leveling, and skill checks within a
 * play campaign. "Member" (party roster entry) vs. "character owner"
 * (`play_campaign_character_owners`) are distinct: a member is added by
 * joinPlayCampaign and defaults to owning their own character, but ownership
 * can be transferred to another campaign member (see transferCharacter).
 */

import { getDb } from '../../db.ts';
import type { ApiResult, JsonValue } from '../../types.ts';
import { isValidIntInRange } from '../../validation.ts';
import { abilityModifierValue, proficiencyBonusValue } from '../character.ts';
import {
  authenticate,
  isActor,
  isApiResult,
  findCampaign,
  findMemberByCharacterId,
  requireParticipant,
  isMember,
  resolveCharacterOwner,
  requireNonEmptyString,
  type MemberRow,
} from './shared.ts';

export function getCharacterSheet(
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

  const isDm = campaign.owner === actor.username;
  if (owner !== actor.username && !isDm) {
    return { status: 403, body: { error: 'only the character owner or dm may read this sheet' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  return {
    status: 200,
    body: {
      character_id: characterId,
      owner,
      name: member.name,
      class: member.class,
      level: 1,
      proficiency_bonus: 2,
      hp_max: 10,
      armor_class: 10,
    } as unknown as JsonValue,
  };
}

const OUTCOME_STATUSES = new Set(['success', 'failure']);

export function damageCharacter(
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

  if (actor.username !== campaign.owner) {
    return { status: 403, body: { error: 'only the owner may apply damage' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  if (!isValidIntInRange(body.amount, 0, 1000000)) {
    return { status: 400, body: { error: 'amount must be a non-negative integer' } };
  }
  const amount = body.amount as number;

  const hpBefore = member.hp_current;
  const hpAfter = Math.max(0, hpBefore - amount);
  let status = member.status;
  let successes = member.death_save_successes;
  let failures = member.death_save_failures;

  if (hpAfter === 0 && member.status === 'conscious') {
    status = 'unconscious';
    successes = 0;
    failures = 0;
  }

  db.prepare(
    'UPDATE play_campaign_members SET hp_current = ?, status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
  ).run(hpAfter, status, successes, failures, campaignId, characterId);

  return {
    status: 200,
    body: {
      character_id: characterId,
      target: characterId,
      hp_before: hpBefore,
      hp_after: hpAfter,
      hp_current: hpAfter,
      hp_max: member.hp_max,
      status,
      damage: amount,
    },
  };
}

export function recordDeathSave(
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

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  if (actor.username !== member.username) {
    return { status: 403, body: { error: 'only the character owner may roll a death save' } };
  }

  if (member.status !== 'unconscious') {
    return { status: 409, body: { error: 'character is not unconscious' } };
  }

  const outcome = body.outcome;
  if (typeof outcome !== 'string' || !OUTCOME_STATUSES.has(outcome)) {
    return { status: 400, body: { error: 'outcome must be "success" or "failure"' } };
  }

  let successes = member.death_save_successes;
  let failures = member.death_save_failures;
  if (outcome === 'success') {
    successes += 1;
  } else {
    failures += 1;
  }

  let status = member.status;
  if (successes >= 3) {
    status = 'stable';
  } else if (failures >= 3) {
    status = 'dead';
  }

  db.prepare(
    'UPDATE play_campaign_members SET status = ?, death_save_successes = ?, death_save_failures = ? WHERE campaign_id = ? AND character_id = ?',
  ).run(status, successes, failures, campaignId, characterId);

  return {
    status: 201,
    body: { character_id: characterId, successes, failures, status },
  };
}

export function getCharacterOwner(
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

  return { status: 200, body: { character_id: characterId, owner } };
}

export function claimCharacter(
  authHeader: string | undefined,
  campaignId: string,
  characterId: string,
  _body: JsonValue,
): ApiResult {
  const actor = authenticate(authHeader);
  if (!isActor(actor)) return actor;

  const db = getDb();
  const campaign = findCampaign(db, campaignId);
  if (isApiResult(campaign)) return campaign;

  const forbidden = requireParticipant(db, campaign, actor, 'not a campaign member');
  if (forbidden) return forbidden;

  const owner = resolveCharacterOwner(db, campaignId, characterId);
  if (owner) {
    return { status: 409, body: { error: 'character is already owned' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)',
  ).run(campaignId, characterId, actor.username);

  return { status: 201, body: { character_id: characterId, owner: actor.username } };
}

export function transferCharacter(
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
    return { status: 403, body: { error: 'only the owner may transfer the character' } };
  }

  const newOwner = requireNonEmptyString(body.new_owner, 'new_owner');
  if (isApiResult(newOwner)) return newOwner;

  if (!isMember(db, campaignId, newOwner)) {
    return { status: 400, body: { error: 'new_owner must be a campaign member' } };
  }

  db.prepare(
    'INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?) ' +
      'ON CONFLICT(campaign_id, character_id) DO UPDATE SET owner = excluded.owner',
  ).run(campaignId, characterId, newOwner);

  return { status: 200, body: { character_id: characterId, owner: newOwner } };
}

const VALID_RACES = new Set([
  'human',
  'elf',
  'dwarf',
  'halfling',
  'gnome',
  'half-elf',
  'half-orc',
  'tiefling',
  'dragonborn',
]);

const VALID_CLASSES = new Set([
  'barbarian',
  'bard',
  'cleric',
  'druid',
  'fighter',
  'monk',
  'paladin',
  'ranger',
  'rogue',
  'sorcerer',
  'warlock',
  'wizard',
]);

const VALID_BACKGROUNDS = new Set([
  'acolyte',
  'charlatan',
  'criminal',
  'entertainer',
  'folk-hero',
  'guild-artisan',
  'hermit',
  'noble',
  'outlander',
  'sage',
  'sailor',
  'soldier',
  'urchin',
]);

const BUILD_ABILITY_KEYS = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

const CLASS_HIT_DIE: Record<string, number> = {
  barbarian: 12,
  bard: 8,
  cleric: 8,
  druid: 8,
  fighter: 10,
  monk: 8,
  paladin: 10,
  ranger: 10,
  rogue: 8,
  sorcerer: 6,
  warlock: 8,
  wizard: 6,
};

export function buildCharacter(
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
    return { status: 403, body: { error: 'only the character owner may build the character' } };
  }

  const race = body.race;
  if (typeof race !== 'string' || !VALID_RACES.has(race)) {
    return { status: 400, body: { error: 'race must be a valid race' } };
  }

  const characterClass = body.class;
  if (typeof characterClass !== 'string' || !VALID_CLASSES.has(characterClass)) {
    return { status: 400, body: { error: 'class must be a valid class' } };
  }

  const background = body.background;
  if (typeof background !== 'string' || !VALID_BACKGROUNDS.has(background)) {
    return { status: 400, body: { error: 'background must be a valid background' } };
  }

  const abilities = body.abilities;
  if (typeof abilities !== 'object' || abilities === null || Array.isArray(abilities)) {
    return { status: 400, body: { error: 'abilities must be an object' } };
  }
  const abilitiesObj = abilities as JsonValue;

  const scores: Record<string, number> = {};
  for (const key of BUILD_ABILITY_KEYS) {
    const score = abilitiesObj[key];
    if (!isValidIntInRange(score, 1, 30)) {
      return { status: 400, body: { error: `abilities.${key} must be an integer from 1 through 30` } };
    }
    scores[key] = score as number;
  }

  const level = 1;
  const conModifier = abilityModifierValue(scores.con);
  const strModifier = abilityModifierValue(scores.str);
  const dexModifier = abilityModifierValue(scores.dex);
  const intModifier = abilityModifierValue(scores.int);
  const wisModifier = abilityModifierValue(scores.wis);
  const chaModifier = abilityModifierValue(scores.cha);
  const hitDie = CLASS_HIT_DIE[characterClass];
  const hpMax = hitDie + conModifier;
  const proficiencyBonusVal = proficiencyBonusValue(level);

  db.prepare(
    'UPDATE play_campaign_members SET class = ?, hp_current = ?, hp_max = ?, level = ?, con_modifier = ?, str_modifier = ?, dex_modifier = ?, int_modifier = ?, wis_modifier = ?, cha_modifier = ? WHERE campaign_id = ? AND character_id = ?',
  ).run(
    characterClass,
    hpMax,
    hpMax,
    level,
    conModifier,
    strModifier,
    dexModifier,
    intModifier,
    wisModifier,
    chaModifier,
    campaignId,
    characterId,
  );

  return {
    status: 200,
    body: {
      character_id: characterId,
      race,
      class: characterClass,
      background,
      level,
      hp_max: hpMax,
      proficiency_bonus: proficiencyBonusVal,
    },
  };
}

export function levelUpCharacter(
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
    return { status: 403, body: { error: 'only the character owner may level up the character' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  if (!isValidIntInRange(body.level, 1, 20)) {
    return { status: 400, body: { error: 'level must be an integer from 1 through 20' } };
  }
  const newLevel = body.level as number;
  if (newLevel !== member.level + 1) {
    return { status: 400, body: { error: 'level must be exactly one higher than the current level' } };
  }

  const hitDie = CLASS_HIT_DIE[member.class] ?? 8;
  const perLevelHp = Math.floor(hitDie / 2) + 1 + member.con_modifier;
  const newHpMax = member.hp_max + perLevelHp;
  const proficiencyBonusVal = proficiencyBonusValue(newLevel);

  db.prepare('UPDATE play_campaign_members SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?').run(
    newLevel,
    newHpMax,
    campaignId,
    characterId,
  );

  return {
    status: 200,
    body: {
      character_id: characterId,
      level: newLevel,
      hp_max: newHpMax,
      hit_dice: `1d${hitDie}`,
      proficiency_bonus: proficiencyBonusVal,
    },
  };
}

const SKILL_ABILITIES: Record<string, string> = {
  acrobatics: 'dex',
  'animal-handling': 'wis',
  arcana: 'int',
  athletics: 'str',
  deception: 'cha',
  history: 'int',
  insight: 'wis',
  intimidation: 'cha',
  investigation: 'int',
  medicine: 'wis',
  nature: 'int',
  perception: 'wis',
  performance: 'cha',
  persuasion: 'cha',
  religion: 'int',
  'sleight-of-hand': 'dex',
  stealth: 'dex',
  survival: 'wis',
};

const ABILITY_MODIFIER_COLUMNS: Record<string, keyof MemberRow> = {
  str: 'str_modifier',
  dex: 'dex_modifier',
  con: 'con_modifier',
  int: 'int_modifier',
  wis: 'wis_modifier',
  cha: 'cha_modifier',
};

export function skillCheck(
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
    return { status: 403, body: { error: 'only the character owner may make a skill check for the character' } };
  }

  const skill = body.skill;
  if (typeof skill !== 'string' || !(skill in SKILL_ABILITIES)) {
    return { status: 400, body: { error: 'skill must be a supported skill' } };
  }

  const ability = body.ability;
  if (typeof ability !== 'string' || !(ability in ABILITY_MODIFIER_COLUMNS)) {
    return { status: 400, body: { error: 'ability must be a supported ability' } };
  }
  if (SKILL_ABILITIES[skill] !== ability) {
    return { status: 400, body: { error: `skill ${skill} does not use ability ${ability}` } };
  }

  const proficient = body.proficient;
  if (typeof proficient !== 'boolean') {
    return { status: 400, body: { error: 'proficient must be a boolean' } };
  }

  const roll = body.roll;
  if (!isValidIntInRange(roll, 1, 20)) {
    return { status: 400, body: { error: 'roll must be an integer from 1 through 20' } };
  }

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  const abilityModifierVal = member[ABILITY_MODIFIER_COLUMNS[ability]] as number;
  const proficiencyBonusVal = proficient ? proficiencyBonusValue(member.level) : 0;
  const modifier = abilityModifierVal + proficiencyBonusVal;
  const total = (roll as number) + modifier;

  return {
    status: 200,
    body: {
      character_id: characterId,
      skill,
      ability,
      modifier,
      total,
    },
  };
}

export function getCharacterStatus(
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

  const member = findMemberByCharacterId(db, campaignId, characterId);
  if (isApiResult(member)) return member;

  return {
    status: 200,
    body: {
      character_id: characterId,
      hp_current: member.hp_current,
      hp_max: member.hp_max,
      status: member.status,
    },
  };
}
