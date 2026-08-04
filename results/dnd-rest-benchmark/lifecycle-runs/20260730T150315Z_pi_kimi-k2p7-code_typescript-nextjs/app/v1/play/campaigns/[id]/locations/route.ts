import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import { createLocation, getPlayCampaign } from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

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
  if (!isNonEmptyString(b.id) || !isNonEmptyString(b.name)) {
    return badRequest();
  }

  const result = createLocation(id, { id: b.id, name: b.name });
  if (!result) {
    return conflict();
  }

  return created(result);
}
