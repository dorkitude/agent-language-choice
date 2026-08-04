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
  createConnection,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString, isPositiveInteger } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; loc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, loc_id: from_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.to_id) || !isPositiveInteger(b.travel_turns)) {
    return badRequest();
  }

  const result = createConnection(id, from_id, {
    to_id: b.to_id,
    travel_turns: b.travel_turns,
  });
  if (!result) {
    return badRequest();
  }

  return created(result);
}
