import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  applyDamageToCharacter,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";
import { isPositiveInteger } from "../../../../../../../lib/validate.js";

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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  if (!isPositiveInteger(parsed.body.amount)) {
    return badRequest();
  }

  const result = applyDamageToCharacter(id, char_id, parsed.body.amount);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
