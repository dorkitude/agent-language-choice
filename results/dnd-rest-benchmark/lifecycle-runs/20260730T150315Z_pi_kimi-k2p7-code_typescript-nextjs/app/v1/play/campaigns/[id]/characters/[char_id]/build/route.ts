import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  validateCharacterBuild,
  type ValidatedCharacterBuild,
} from "../../../../../../../lib/engine.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getCharacterOwner,
  getPlayCampaign,
  updateCharacterBuild,
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

  const validated = validateCharacterBuild(parsed.body) as ValidatedCharacterBuild | null;
  if (!validated) {
    return badRequest();
  }

  const stored = updateCharacterBuild(id, char_id, {
    race: validated.race,
    class: validated.class,
    background: validated.background,
    abilities: validated.abilities,
    level: validated.level,
    hp_max: validated.hp_max,
  });

  if (!stored) {
    return notFound();
  }

  return ok({
    character_id: char_id,
    race: validated.race,
    class: validated.class,
    background: validated.background,
    level: validated.level,
    hp_max: validated.hp_max,
    proficiency_bonus: validated.proficiency_bonus,
  });
}
