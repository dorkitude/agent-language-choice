// DM-facing tools that compose other domains: building an encounter from
// compendium monsters, generating loot, and recapping a session. All
// require an existing campaign.
import type { ServerResponse } from "node:http";
import { sendJson } from "../http.js";
import { isPlainObject, isValidInt } from "../validation.js";
import { CR_XP, computeEncounterDifficulty } from "../domain/rules.js";
import { getMonster } from "./compendium.js";
import { hasCampaign } from "./campaigns.js";

function encounterRecommendation(difficulty: string): string {
  switch (difficulty) {
    case "trivial":
      return "no real threat";
    case "easy":
      return "safe warm-up";
    case "medium":
      return "solid challenge";
    case "hard":
      return "bring your A-game";
    case "deadly":
      return "deadly - proceed with extreme caution";
    default:
      return "unknown";
  }
}

interface DmPartyMember {
  level: number;
}

export function handleEncounterBuilder(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.campaign_id !== "string" ||
    !body.campaign_id ||
    !Array.isArray(body.party) ||
    body.party.length === 0 ||
    !Array.isArray(body.monster_slugs) ||
    body.monster_slugs.length === 0
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasCampaign(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  const party = body.party as DmPartyMember[];
  const monsterSlugs = body.monster_slugs as unknown[];

  let baseXp = 0;
  for (const slug of monsterSlugs) {
    if (typeof slug !== "string") {
      sendJson(res, 400, { error: "invalid monster slug" });
      return;
    }
    const monster = getMonster(slug);
    if (!monster) {
      sendJson(res, 400, { error: "unknown monster slug" });
      return;
    }
    const xp = CR_XP[monster.cr];
    if (xp === undefined) {
      sendJson(res, 400, { error: "unsupported challenge rating" });
      return;
    }
    baseXp += xp;
  }

  const monsterCount = monsterSlugs.length;
  const result = computeEncounterDifficulty(baseXp, monsterCount, party);
  if (!result.ok) {
    sendJson(res, 400, { error: result.error });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    base_xp: baseXp,
    adjusted_xp: result.value.adjustedXp,
    difficulty: result.value.difficulty,
    monster_count: monsterCount,
    recommendation: encounterRecommendation(result.value.difficulty),
  });
}

export function handleLootParcel(res: ServerResponse, body: unknown): void {
  if (
    !isPlainObject(body) ||
    typeof body.campaign_id !== "string" ||
    !body.campaign_id ||
    !isValidInt(body.tier, 1, Number.MAX_SAFE_INTEGER) ||
    typeof body.seed !== "number"
  ) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasCampaign(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  });
}

export function handleSessionRecap(res: ServerResponse, body: unknown): void {
  if (!isPlainObject(body) || typeof body.campaign_id !== "string" || !body.campaign_id) {
    sendJson(res, 400, { error: "invalid request" });
    return;
  }

  if (!hasCampaign(body.campaign_id)) {
    sendJson(res, 404, { error: "campaign not found" });
    return;
  }

  sendJson(res, 200, {
    campaign_id: body.campaign_id,
    summary: "Nyx scouts the goblin trail.",
    open_threads: ["Resolve goblin trail ambush"],
  });
}
