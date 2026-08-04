import { ServerResponse } from 'node:http';
import { sendJSON } from '../http-utils.js';
import { abilityModifier, proficiencyBonus } from '../rules.js';
import { isValidAbilityScore, isValidLevel } from '../validators.js';

export function handleAbilityModifier(res: ServerResponse, _params: unknown, body: unknown): void {
  const { score } = body as { score?: unknown };
  if (!isValidAbilityScore(score)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  sendJSON(res, 200, { score, modifier: abilityModifier(score) });
}

export function handleProficiencyBonus(res: ServerResponse, _params: unknown, body: unknown): void {
  const { level } = body as { level?: unknown };
  if (!isValidLevel(level)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  sendJSON(res, 200, { level, proficiency_bonus: proficiencyBonus(level) });
}

export function handleDerivedStats(res: ServerResponse, _params: unknown, body: unknown): void {
  const { level, abilities, armor } = body as {
    level?: unknown;
    abilities?: unknown;
    armor?: unknown;
  };

  if (!isValidLevel(level)) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  if (typeof abilities !== 'object' || abilities == null) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'] as const;
  const modifiers: Record<string, number> = {};
  for (const name of abilityNames) {
    const score = (abilities as Record<string, unknown>)[name];
    if (!isValidAbilityScore(score)) {
      sendJSON(res, 400, { error: 'invalid input' });
      return;
    }
    modifiers[name] = abilityModifier(score);
  }

  if (typeof armor !== 'object' || armor == null) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }
  const armorObj = armor as Record<string, unknown>;
  if (
    typeof armorObj.base !== 'number' ||
    !Number.isInteger(armorObj.base) ||
    typeof armorObj.shield !== 'boolean' ||
    typeof armorObj.dex_cap !== 'number' ||
    !Number.isInteger(armorObj.dex_cap)
  ) {
    sendJSON(res, 400, { error: 'invalid input' });
    return;
  }

  const shieldBonus = armorObj.shield ? 2 : 0;
  const armorClass = armorObj.base + Math.min(modifiers.dex, armorObj.dex_cap) + shieldBonus;
  const hpMax = level * (6 + modifiers.con);

  sendJSON(res, 200, {
    level,
    proficiency_bonus: proficiencyBonus(level),
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
