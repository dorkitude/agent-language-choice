import { requireBearerAuth } from "../../../../../../../../../lib/auth.js";
import {
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../../lib/http.js";
import {
  getDowntimeActivity,
  getDowntimeAllocation,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  {
    params,
  }: {
    params: Promise<{ id: string; char_id: string; activity_id: string }>;
  }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id, activity_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isOwner = campaign.owner === auth.user.username;
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const activity = getDowntimeActivity(id, activity_id);
  if (!activity) {
    return notFound();
  }

  const allocation = getDowntimeAllocation(id, char_id, activity_id);
  if (!allocation) {
    return notFound();
  }

  return ok(allocation);
}
