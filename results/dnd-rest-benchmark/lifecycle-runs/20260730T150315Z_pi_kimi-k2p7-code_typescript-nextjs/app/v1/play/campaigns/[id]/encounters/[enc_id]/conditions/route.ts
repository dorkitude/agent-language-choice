import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  addPlayCampaignEncounterCondition,
  getPlayCampaign,
  getPlayCampaignEncounter,
} from "../../../../../../../lib/storage.js";
import { isInteger, isNonEmptyString } from "../../../../../../../lib/validate.js";

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
    !isNonEmptyString(b.target) ||
    !isNonEmptyString(b.condition) ||
    !isInteger(b.duration_rounds) ||
    b.duration_rounds <= 0
  ) {
    return badRequest();
  }

  const result = addPlayCampaignEncounterCondition(
    id,
    enc_id,
    b.target,
    b.condition,
    b.duration_rounds
  );
  if (!result) {
    return notFound();
  }

  return created(result);
}
