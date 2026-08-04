import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { abilityModifier, proficiencyBonus } from "../../../../../../../lib/engine.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getCharacterLevelUpState,
  getCharacterOwner,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";

const VALID_SKILLS = new Set([
  "acrobatics",
  "animal-handling",
  "arcana",
  "athletics",
  "deception",
  "history",
  "insight",
  "intimidation",
  "investigation",
  "medicine",
  "nature",
  "perception",
  "performance",
  "persuasion",
  "religion",
  "sleight-of-hand",
  "stealth",
  "survival",
]);

const VALID_ABILITIES = new Set(["str", "dex", "con", "int", "wis", "cha"]);

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, char_id);
  if (!ownerRecord) {
    return notFound();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const skill = parsed.body.skill;
  const ability = parsed.body.ability;
  const proficient = parsed.body.proficient;
  const roll = Number(parsed.body.roll);

  if (
    typeof skill !== "string" ||
    typeof ability !== "string" ||
    typeof proficient !== "boolean" ||
    !Number.isInteger(roll)
  ) {
    return badRequest();
  }

  const normalizedSkill = skill.toLowerCase().replace(/[\s_]+/g, "-");
  if (!VALID_SKILLS.has(normalizedSkill)) {
    return badRequest();
  }

  const normalizedAbility = ability.toLowerCase();
  if (!VALID_ABILITIES.has(normalizedAbility)) {
    return badRequest();
  }

  const state = getCharacterLevelUpState(id, char_id);
  if (!state) {
    return badRequest();
  }

  const abilityScore = state.abilities[normalizedAbility as keyof typeof state.abilities];
  const modifier =
    abilityModifier(abilityScore) + (proficient ? proficiencyBonus(state.level) : 0);
  const total = roll + modifier;

  return ok({
    character_id: char_id,
    skill,
    ability,
    modifier,
    total,
  });
}
