import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  conflict,
  created,
  forbidden,
  notFound,
} from "../../../../../../../../lib/http.js";
import {
  awardPlayCampaignQuestRewards,
  getPlayCampaign,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, quest_id } = await params;
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const result = awardPlayCampaignQuestRewards(id, quest_id);
  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}
