import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { ABILITY_KEYS, AbilityKey, SKILL_ABILITY, proficiencyBonus } from "../../../../../../characters/rules.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId } from "../../../../../store.js";

const STARTING_LEVEL = 1;

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
      { error: `only the owner of character ${characterId} may resolve a skill check` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    skill?: unknown;
    ability?: unknown;
    proficient?: unknown;
    roll?: unknown;
  };

  const { skill, ability, proficient, roll } = body ?? {};

  if (typeof skill !== "string" || !(skill in SKILL_ABILITY)) {
    return Response.json({ error: "skill must be a supported skill" }, { status: 400 });
  }

  if (typeof ability !== "string" || !ABILITY_KEYS.includes(ability as AbilityKey)) {
    return Response.json({ error: "ability must be a valid ability" }, { status: 400 });
  }

  if (typeof proficient !== "boolean") {
    return Response.json({ error: "proficient must be a boolean" }, { status: 400 });
  }

  if (typeof roll !== "number" || !Number.isFinite(roll)) {
    return Response.json({ error: "roll must be a number" }, { status: 400 });
  }

  const abilityKey = ability as AbilityKey;
  const abilityModifierValue = member.ability_modifiers?.[abilityKey] ?? 0;
  const level = member.level ?? STARTING_LEVEL;
  const modifier = abilityModifierValue + (proficient ? proficiencyBonus(level) : 0);
  const total = roll + modifier;

  return Response.json(
    {
      character_id: characterId,
      skill,
      ability: abilityKey,
      modifier,
      total,
    },
    { status: 200 },
  );
}
