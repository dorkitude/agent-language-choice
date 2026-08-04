import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { CLASS_HIT_DIE, fixedHitDieRoll, proficiencyBonus } from "../../../../../../characters/rules.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, updatePlayMember } from "../../../../../store.js";

const DEFAULT_HIT_DIE = 8;
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
      { error: `only the owner of character ${characterId} may level it up` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { level?: unknown };

  if (typeof body.level !== "number" || !Number.isInteger(body.level)) {
    return Response.json({ error: "level must be an integer" }, { status: 400 });
  }

  const currentLevel = member.level ?? STARTING_LEVEL;
  const nextLevel = body.level;

  if (nextLevel !== currentLevel + 1) {
    return Response.json(
      { error: `level must be exactly one higher than the current level (${currentLevel})` },
      { status: 400 },
    );
  }

  const hitDie = member.class ? (CLASS_HIT_DIE[member.class] ?? DEFAULT_HIT_DIE) : DEFAULT_HIT_DIE;
  const conModifier = member.con_modifier ?? 0;
  const hpMaxBefore = member.hp_max ?? hitDie + conModifier;
  const hpGain = fixedHitDieRoll(hitDie) + conModifier;
  const hpMax = hpMaxBefore + hpGain;

  const updated = {
    ...member,
    level: nextLevel,
    hp_max: hpMax,
  };
  updatePlayMember(updated);

  return Response.json(
    {
      character_id: characterId,
      level: nextLevel,
      hp_max: hpMax,
      hit_dice: `1d${hitDie}`,
      proficiency_bonus: proficiencyBonus(nextLevel),
    },
    { status: 200 },
  );
}
