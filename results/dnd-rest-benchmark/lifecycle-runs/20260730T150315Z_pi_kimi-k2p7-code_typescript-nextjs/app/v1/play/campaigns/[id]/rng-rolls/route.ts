import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  appendRngRoll,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import { isInteger, isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (
    campaign.owner !== auth.user.username &&
    !getPlayCampaignMember(id, auth.user.username)
  ) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.roll_id) ||
    !isInteger(b.sides) ||
    b.sides < 2 ||
    b.sides > 100
  ) {
    return badRequest();
  }

  const result = appendRngRoll(id, {
    roll_id: b.roll_id,
    sides: b.sides,
  });
  if (result === null) {
    return notFound();
  }
  if (result === "missing_seed") {
    return conflict();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return created(result);
}
