// Input validation helpers. Each function is a TypeScript type guard so the
// caller can narrow values without repeated casts. These intentionally match
// the validation rules inherited from the original implementation.

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'string');
}

export function isAbilityScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 30;
}

export function isLevel(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 20;
}

export function isValidRole(value: unknown): value is 'dm' | 'player' {
  return value === 'dm' || value === 'player';
}

// Usernames are limited to lowercase letters, digits, underscore, and hyphen,
// with a length between 2 and 32 characters. This constraint is preserved from
// the original auth suite.
export const USERNAME_RE = /^[a-z0-9_-]{2,32}$/;

export function isQuestStatus(value: unknown): value is 'active' | 'completed' | 'blocked' {
  return value === 'active' || value === 'completed' || value === 'blocked';
}

export function isStance(value: unknown): value is string {
  return isNonEmptyString(value);
}

export function isDisposition(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

const COMBAT_ACTION_TYPES = ['attack', 'help', 'dodge', 'ready'] as const;

export type CombatActionType = (typeof COMBAT_ACTION_TYPES)[number];

export function isCombatActionType(value: unknown): value is CombatActionType {
  return typeof value === 'string' && COMBAT_ACTION_TYPES.includes(value as CombatActionType);
}

export type DeathSaveOutcome = 'success' | 'failure';

export function isDeathSaveOutcome(value: unknown): value is DeathSaveOutcome {
  return value === 'success' || value === 'failure';
}
