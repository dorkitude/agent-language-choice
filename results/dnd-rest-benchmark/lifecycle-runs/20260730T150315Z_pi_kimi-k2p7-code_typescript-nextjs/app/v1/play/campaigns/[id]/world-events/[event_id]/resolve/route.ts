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
  getPlayCampaign,
  resolvePlayCampaignWorldEvent,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; event_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, event_id } = await params;
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
  if (!isNonEmptyString(b.text)) {
    return badRequest();
  }

  const result = resolvePlayCampaignWorldEvent(id, event_id, b.text);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "bad_request") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}
