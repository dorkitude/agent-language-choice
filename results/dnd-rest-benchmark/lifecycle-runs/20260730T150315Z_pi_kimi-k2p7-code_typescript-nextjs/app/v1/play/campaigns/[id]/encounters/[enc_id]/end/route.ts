import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  conflict,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../lib/http.js";
import {
  endPlayCampaignEncounter,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";

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

  const result = endPlayCampaignEncounter(id, enc_id);
  if (result === "not_in_combat") {
    return conflict();
  }
  if (!result) {
    return notFound();
  }

  return ok(result);
}
