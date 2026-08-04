import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { abilityModifier, proficiencyBonus, CLASS_HIT_DIE } from "../../../../../../characters/rules.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, updatePlayMember } from "../../../../../store.js";

const VALID_RACES = new Set([
  "human",
  "elf",
  "dwarf",
  "halfling",
  "dragonborn",
  "gnome",
  "half-elf",
  "half-orc",
  "tiefling",
]);

const HIT_DICE = CLASS_HIT_DIE;

const VALID_BACKGROUNDS = new Set([
  "acolyte",
  "charlatan",
  "criminal",
  "entertainer",
  "folk hero",
  "guild artisan",
  "hermit",
  "noble",
  "outlander",
  "sage",
  "sailor",
  "soldier",
  "urchin",
]);

const ABILITY_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;
type AbilityKey = (typeof ABILITY_KEYS)[number];

const LEVEL_ONE = 1;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const username = session.user.username;
  const currentOwner = member.owner ?? member.username;
  if (currentOwner !== username) {
    return Response.json(
      { error: `only the owner of character ${characterId} may build it` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { race, class: charClass, background, abilities } = (body ?? {}) as {
    race?: unknown;
    class?: unknown;
    background?: unknown;
    abilities?: unknown;
  };

  if (typeof race !== "string" || !VALID_RACES.has(race)) {
    return Response.json({ error: "race must be a valid race" }, { status: 400 });
  }

  if (typeof charClass !== "string" || !(charClass in HIT_DICE)) {
    return Response.json({ error: "class must be a valid class" }, { status: 400 });
  }

  if (typeof background !== "string" || !VALID_BACKGROUNDS.has(background)) {
    return Response.json({ error: "background must be a valid background" }, { status: 400 });
  }

  if (typeof abilities !== "object" || abilities === null || Array.isArray(abilities)) {
    return Response.json({ error: "abilities must be an object" }, { status: 400 });
  }

  const abilityScores = abilities as Record<string, unknown>;
  const modifiers: Record<AbilityKey, number> = {} as Record<AbilityKey, number>;
  for (const key of ABILITY_KEYS) {
    const score = abilityScores[key];
    if (typeof score !== "number" || !Number.isInteger(score) || score < 1 || score > 30) {
      return Response.json(
        { error: `abilities.${key} must be an integer from 1 through 30` },
        { status: 400 },
      );
    }
    modifiers[key] = abilityModifier(score);
  }

  const hpMax = HIT_DICE[charClass] + modifiers.con;

  const updated = {
    ...member,
    class: charClass,
    race,
    background,
    hp_max: hpMax,
    level: LEVEL_ONE,
    con_modifier: modifiers.con,
    ability_modifiers: modifiers,
  };
  updatePlayMember(updated);

  return Response.json(
    {
      character_id: characterId,
      race,
      class: charClass,
      background,
      level: LEVEL_ONE,
      hp_max: hpMax,
      proficiency_bonus: proficiencyBonus(LEVEL_ONE),
    },
    { status: 200 },
  );
}
