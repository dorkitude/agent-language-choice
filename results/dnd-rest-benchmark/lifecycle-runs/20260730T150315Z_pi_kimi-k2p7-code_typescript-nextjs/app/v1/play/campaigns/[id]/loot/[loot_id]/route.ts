import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../lib/http.js";
import {
  getLoot,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, loot_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  const isOwner = campaign.owner === auth.user.username;

  if (!isMember && !isOwner) {
    return forbidden();
  }

  const record = getLoot(id, loot_id);
  if (!record) {
    return notFound();
  }

  return ok(record);
}
