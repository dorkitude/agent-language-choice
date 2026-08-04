import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignEncounter,
  removePlayCampaignEncounterMonster,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string; monster_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, enc_id, monster_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const encounter = getPlayCampaignEncounter(id, enc_id);
  if (!encounter) {
    return notFound();
  }

  const result = removePlayCampaignEncounterMonster(id, enc_id, monster_id);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
