import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  applyDamageToEncounterCombatant,
  getPlayCampaign,
  getPlayCampaignEncounter,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString, isPositiveInteger } from "../../../../../../../lib/validate.js";

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
  if (!isNonEmptyString(b.target) || !isPositiveInteger(b.amount)) {
    return badRequest();
  }

  const result = applyDamageToEncounterCombatant(id, enc_id, b.target, b.amount);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
