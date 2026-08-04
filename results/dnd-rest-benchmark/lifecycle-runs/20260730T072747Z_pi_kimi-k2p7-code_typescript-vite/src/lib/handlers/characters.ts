import type { ServerResponse } from 'node:http';
import { sendError, sendJson } from '../http.js';
import { abilityModifier, proficiencyBonus } from '../rules.js';
import { isAbilityScore, isLevel } from '../validation.js';

export function handleAbilityModifier(body: unknown, res: ServerResponse): boolean {
  const score = (body as any)?.score;
  if (!isAbilityScore(score)) {
    sendError(res, 400, 'invalid score');
    return true;
  }
  sendJson(res, 200, { score, modifier: abilityModifier(score) });
  return true;
}

export function handleProficiency(body: unknown, res: ServerResponse): boolean {
  const level = (body as any)?.level;
  if (!isLevel(level)) {
    sendError(res, 400, 'invalid level');
    return true;
  }
  sendJson(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
  return true;
}

export function handleDerivedStats(body: unknown, res: ServerResponse): boolean {
  const b = body as any;
  if (!b || typeof b !== 'object') {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const { level, abilities, armor } = b;
  if (!isLevel(level) || !abilities || typeof abilities !== 'object' || !armor || typeof armor !== 'object') {
    sendError(res, 400, 'invalid request');
    return true;
  }
  const abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
  const modifiers: Record<string, number> = {};
  for (const key of abilityNames) {
    const score = abilities[key];
    if (!isAbilityScore(score)) {
      sendError(res, 400, 'invalid ability score');
      return true;
    }
    modifiers[key] = abilityModifier(score);
  }
  const base = armor.base;
  const dexCap = armor.dex_cap;
  const shield = armor.shield;
  if (!Number.isInteger(base) || !Number.isInteger(dexCap) || typeof shield !== 'boolean') {
    sendError(res, 400, 'invalid armor');
    return true;
  }
  const shieldBonus = shield ? 2 : 0;
  const hpMax = level * (6 + modifiers.con);
  const armorClass = base + Math.min(modifiers.dex, dexCap) + shieldBonus;
  sendJson(res, 200, {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
  return true;
}
