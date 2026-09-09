import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  seedPlayCampaignFixture,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  if (!isNonEmptyString(parsed.body.fixture_id)) {
    return badRequest();
  }

  const result = seedPlayCampaignFixture(id, parsed.body.fixture_id);
  if (result === null) {
    return notFound();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  if (result.created) {
    return created(result.state);
  }
  return ok(result.state);
}
