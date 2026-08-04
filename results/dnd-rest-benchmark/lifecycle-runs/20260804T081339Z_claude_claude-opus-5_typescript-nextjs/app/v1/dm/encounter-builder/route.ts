import { getCampaign, listCharacters } from "../../../../lib/campaigns";
import { getMonster } from "../../../../lib/compendium";
import { recommendationFor } from "../../../../lib/dm";
import {
  CR_XP,
  crKey,
  difficultyFor,
  multiplierFor,
  sumThresholds,
} from "../../../../lib/encounters";
import { badRequest, json, notFound, readObject } from "../../../../lib/http";
import { asLevel, isObjectLike, isValidId, isValidSlug } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

/**
 * Campaign-aware encounter sizing. Shares its XP math with the stateless
 * `/v1/encounters/adjusted-xp` so both report identical numbers, but resolves
 * monsters from the compendium and can default the party to the stored roster.
 */
export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const campaignId = body.campaign_id;
  if (!isValidId(campaignId)) return badRequest("campaign_id must be a valid identifier");
  if (!getCampaign(campaignId)) return notFound("campaign not found");

  const slugs = body.monster_slugs;
  if (!Array.isArray(slugs) || slugs.length === 0) {
    return badRequest("monster_slugs must be a non-empty array");
  }

  const levels = partyLevels(campaignId, body.party);
  if (typeof levels === "string") return badRequest(levels);

  const summed = sumThresholds(levels);
  if ("unsupportedLevel" in summed) {
    return badRequest(`unsupported party level: ${summed.unsupportedLevel}`);
  }

  let baseXp = 0;
  for (const slug of slugs) {
    if (!isValidSlug(slug)) {
      return badRequest("monster slugs must be 1-64 characters of [A-Za-z0-9_-]");
    }
    const monster = getMonster(slug);
    if (!monster) return notFound(`monster not found: ${slug}`);
    const key = crKey(monster.cr);
    if (key === undefined) return badRequest(`unsupported challenge rating for ${slug}`);
    baseXp += CR_XP[key]!;
  }

  // Each slug counts once — repeat a slug to field two of the same monster.
  const monsterCount = slugs.length;
  const adjustedXp = baseXp * multiplierFor(monsterCount);
  const difficulty = difficultyFor(adjustedXp, summed.thresholds);

  return json({
    campaign_id: campaignId,
    base_xp: baseXp,
    adjusted_xp: adjustedXp,
    difficulty,
    monster_count: monsterCount,
    recommendation: recommendationFor(difficulty),
  });
}

/**
 * Resolve the party levels, falling back to the campaign's stored roster when
 * the caller does not spell out a party. Returns an error message string on
 * invalid input.
 */
function partyLevels(campaignId: string, party: unknown): number[] | string {
  if (party === undefined || party === null) {
    const levels = listCharacters(campaignId).map((character) => character.level);
    if (levels.length === 0) return "party is required for a campaign with no characters";
    return levels;
  }

  if (!Array.isArray(party) || party.length === 0) {
    return "party must be a non-empty array";
  }

  const levels: number[] = [];
  for (const member of party) {
    if (!isObjectLike(member)) return "party members must be objects";
    const level = asLevel(member.level);
    if (level === undefined) return "party member level must be a positive integer";
    levels.push(level);
  }
  return levels;
}
