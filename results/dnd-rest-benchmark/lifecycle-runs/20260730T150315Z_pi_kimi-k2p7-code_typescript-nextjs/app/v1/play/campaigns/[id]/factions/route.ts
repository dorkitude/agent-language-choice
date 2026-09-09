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
  createPlayCampaignFaction,
  getPlayCampaign,
} from "../../../../../lib/storage.js";

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
    typeof b.faction_id !== "string" ||
    b.faction_id.length === 0 ||
    typeof b.name !== "string" ||
    b.name.length === 0
  ) {
    return badRequest();
  }

  const result = createPlayCampaignFaction(id, {
    faction_id: b.faction_id,
    name: b.name,
  });

  if (!result) {
    return conflict();
  }

  return created({
    faction_id: result.faction_id,
    name: result.name,
  });
}
