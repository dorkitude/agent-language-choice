import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  addPlayCampaignEncounterMonster,
  getPlayCampaign,
  getPlayCampaignEncounter,
} from "../../../../../../../lib/storage.js";
import { isInteger, isNonEmptyString, isPositiveInteger } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, enc_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const encounter = getPlayCampaignEncounter(id, enc_id);
  if (!encounter) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.monster_id) ||
    !isNonEmptyString(b.name) ||
    !isPositiveInteger(b.hp_max) ||
    !isInteger(b.initiative)
  ) {
    return badRequest();
  }

  const result = addPlayCampaignEncounterMonster(id, enc_id, {
    monster_id: b.monster_id,
    name: b.name,
    hp_max: b.hp_max,
    initiative: b.initiative,
  });

  if (!result) {
    return conflict();
  }

  return created(result);
}
