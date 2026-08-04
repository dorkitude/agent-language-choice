// Standalone encounter-difficulty math (/v1/encounters, /v1/initiative).
// The DM-facing encounter builder in routes/dm.ts reuses computeEncounterDifficulty
// but resolves monsters from the compendium instead of taking CR/count pairs directly.
import type { ServerResponse } from "node:http";
import { sendJson } from "../http.js";
import { isPlainObject } from "../validation.js";
import { CR_XP, computeEncounterDifficulty, compareInitiative } from "../domain/rules.js";

interface MonsterTally {
  cr: string;
  count: number;
}

interface PartyMember {
  level: number;
}

export function handleAdjustedXp(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || !Array.isArray(body.party) || !Array.isArray(body.monsters)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const party = body.party as PartyMember[];
  const monsters = body.monsters as MonsterTally[];

  let baseXp = 0;
  let monsterCount = 0;
  for (const monster of monsters) {
    const xp = CR_XP[String(monster.cr)];
    if (xp === undefined || typeof monster.count !== "number") {
      sendJson(res, 400, { error: "unsupported challenge rating" });
      return;
    }
    baseXp += xp * monster.count;
    monsterCount += monster.count;
  }

  const result = computeEncounterDifficulty(baseXp, monsterCount, party);
  if (!result.ok) {
    sendJson(res, 400, { error: result.error });
    return;
  }

  sendJson(res, 200, {
    base_xp: baseXp,
    monster_count: monsterCount,
    multiplier: result.value.multiplier,
    adjusted_xp: result.value.adjustedXp,
    difficulty: result.value.difficulty,
    thresholds: result.value.thresholds,
  });
}

interface Combatant {
  name: string;
  dex: number;
  roll: number;
}

export function handleInitiativeOrder(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || !Array.isArray(body.combatants)) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  const combatants = body.combatants as Combatant[];
  const scored = combatants.map((combatant) => ({
    name: combatant.name,
    dex: combatant.dex,
    score: combatant.roll + combatant.dex,
  }));

  scored.sort(compareInitiative);

  sendJson(res, 200, {
    order: scored.map(({ name, score }) => ({ name, score })),
  });
}
