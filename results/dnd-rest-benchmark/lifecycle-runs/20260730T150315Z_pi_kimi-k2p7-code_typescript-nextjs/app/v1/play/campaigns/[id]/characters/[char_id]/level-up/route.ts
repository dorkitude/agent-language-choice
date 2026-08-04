import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { computeLevelUp } from "../../../../../../../lib/engine.js";
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
  levelUpCharacter,
} from "../../../../../../../lib/storage.js";

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

  const level = parsed.body.level;
  if (
    typeof level !== "number" ||
    !Number.isInteger(level) ||
    level < 2 ||
    level > 20
  ) {
    return badRequest();
  }

  const state = getCharacterLevelUpState(id, char_id);
  if (!state) {
    return badRequest();
  }

  if (level !== state.level + 1) {
    return badRequest();
  }

  const result = computeLevelUp(
    state.level,
    state.hp_max,
    state.class,
    state.abilities
  );
  if (!result) {
    return badRequest();
  }

  const updated = levelUpCharacter(id, char_id, result.level, result.hp_max);
  if (!updated) {
    return notFound();
  }

  return ok({
    character_id: char_id,
    level: result.level,
    hp_max: result.hp_max,
    hit_dice: result.hit_dice,
    proficiency_bonus: result.proficiency_bonus,
  });
}
