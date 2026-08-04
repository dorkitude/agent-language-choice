// Stateless character math: ability modifiers, proficiency bonus, and the
// combined derived-stats (HP/AC) calculation. No persistence.
import type { ServerResponse } from "node:http";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { abilityModifier, proficiencyBonus } from "../domain/rules.js";

export function handleAbilityModifier(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || !isValidInt(body.score, 1, 30)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  sendJson(res, 200, { score: body.score, modifier: abilityModifier(body.score) });
}

export function handleProficiency(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || !isValidInt(body.level, 1, 20)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  sendJson(res, 200, { level: body.level, proficiency_bonus: proficiencyBonus(body.level) });
}

interface Abilities {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

const ABILITY_KEYS: (keyof Abilities)[] = ["str", "dex", "con", "int", "wis", "cha"];

export function handleDerivedStats(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || !isValidInt(body.level, 1, 20)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!isPlainObject(body.abilities)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const abilitiesInput = body.abilities;
  for (const key of ABILITY_KEYS) {
    if (typeof abilitiesInput[key] !== "number" || !Number.isInteger(abilitiesInput[key])) {
      sendJson(res, 400, { error: "invalid request" });
      return;
    }
  }

  if (!isPlainObject(body.armor) || typeof body.armor.base !== "number" || typeof body.armor.dex_cap !== "number") {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const abilities = abilitiesInput as unknown as Abilities;
  const modifiers = {} as Abilities;
  for (const key of ABILITY_KEYS) {
    modifiers[key] = abilityModifier(abilities[key]);
  }

  const level = body.level as number;
  const bonus = proficiencyBonus(level);
  const hpMax = level * (6 + modifiers.con);
  const shieldBonus = body.armor.shield === true ? 2 : 0;
  const armorClass = body.armor.base + Math.min(modifiers.dex, body.armor.dex_cap) + shieldBonus;

  sendJson(res, 200, {
    level,
    proficiency_bonus: bonus,
    hp_max: hpMax,
    armor_class: armorClass,
    modifiers,
  });
}
