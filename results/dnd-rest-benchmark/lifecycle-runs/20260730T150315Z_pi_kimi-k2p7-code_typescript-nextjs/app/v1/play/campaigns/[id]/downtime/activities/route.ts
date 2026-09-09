import { requireBearerAuth } from "../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../lib/http.js";
import {
  createDowntimeActivity,
  getPlayCampaign,
} from "../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

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
  if (
    !isNonEmptyString(b.activity_id) ||
    !isNonEmptyString(b.name) ||
    !Number.isInteger(b.cycles_required) ||
    (b.cycles_required as number) < 1 ||
    (b.cycles_required as number) > 10
  ) {
    return badRequest();
  }

  const result = createDowntimeActivity(id, {
    activity_id: b.activity_id as string,
    name: b.name as string,
    cycles_required: b.cycles_required as number,
  });

  if (result === null) {
    return conflict();
  }

  return created(result);
}
