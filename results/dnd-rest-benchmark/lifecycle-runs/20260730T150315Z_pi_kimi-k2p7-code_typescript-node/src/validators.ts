import { classHitDie } from './rules.js';
import type { Combatant, LootItem, QuestStatus, Role } from './types.js';

// Usernames are lowercase alphanumeric with underscores/hyphens, 2-32 chars.
const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

/** True if `value` is an array of strings. */
export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string');
}

export function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

export function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

export function isValidLevel(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 20;
}

export function isValidAbilityScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 30;
}

export function isValidCombatant(c: unknown): c is Combatant {
  return (
    typeof c === 'object' &&
    c !== null &&
    typeof (c as Record<string, unknown>).name === 'string' &&
    typeof (c as Record<string, unknown>).dex === 'number' &&
    Number.isFinite((c as Record<string, unknown>).dex) &&
    typeof (c as Record<string, unknown>).roll === 'number' &&
    Number.isFinite((c as Record<string, unknown>).roll)
  );
}

/** Username must match the allowed character set and length. */
export function isValidUsername(value: unknown): value is string {
  return typeof value === 'string' && USERNAME_RE.test(value);
}

/** Password must be at least 8 characters. */
export function isValidPassword(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 8;
}

/** Only `dm` and `player` are valid user roles. */
export function isValidRole(value: unknown): value is Role {
  return value === 'dm' || value === 'player';
}

export function isValidDiceCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

export function isString(value: unknown): value is string {
  return typeof value === 'string';
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function isValidQuestStatus(value: unknown): value is QuestStatus {
  return value === 'active' || value === 'completed' || value === 'blocked';
}

export function isValidFactionStance(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function isValidDisposition(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isValidDeathSaveOutcome(value: unknown): value is 'success' | 'failure' {
  return value === 'success' || value === 'failure';
}

/** True for a valid loot item with a non-empty slug and positive quantity. */
export function isValidLootItem(value: unknown): value is LootItem {
  return (
    typeof value === 'object' &&
    value !== null &&
    isNonEmptyString((value as Record<string, unknown>).slug) &&
    isPositiveInteger((value as Record<string, unknown>).quantity)
  );
}

/** True for an array of valid loot items. */
export function isValidLootArray(value: unknown): value is LootItem[] {
  return Array.isArray(value) && value.every(isValidLootItem);
}

/** True for a non-empty ISO-8601 string that includes a `T` separator. */
export function isValidISOTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0) return false;
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && value.includes('T');
}

const VALID_RACES = new Set([
  'dragonborn',
  'dwarf',
  'elf',
  'gnome',
  'half-elf',
  'half-orc',
  'halfling',
  'human',
  'tiefling',
]);

const VALID_BACKGROUNDS = new Set([
  'acolyte',
  'charlatan',
  'criminal',
  'entertainer',
  'folk hero',
  'folk-hero',
  'guild artisan',
  'guild-artisan',
  'hermit',
  'noble',
  'outlander',
  'sage',
  'sailor',
  'soldier',
  'urchin',
]);

const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;

/** True for a recognised 5e race. */
export function isValidRace(value: unknown): value is string {
  return typeof value === 'string' && VALID_RACES.has(value.toLowerCase());
}

/** True for a recognised 5e class (with a known hit die). */
export function isValidClass(value: unknown): value is string {
  return typeof value === 'string' && classHitDie(value.toLowerCase()) !== null;
}

/** True for a recognised 5e background. */
export function isValidBackground(value: unknown): value is string {
  return typeof value === 'string' && VALID_BACKGROUNDS.has(value.toLowerCase());
}

/** True when all six ability scores are integers between 1 and 30. */
export function isValidAbilityScores(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const scores = value as Record<string, unknown>;
  for (const name of ABILITY_NAMES) {
    if (!isValidAbilityScore(scores[name])) return false;
  }
  return true;
}
