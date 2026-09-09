import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  forbidden,
  notFound,
  ok,
} from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignSafetyEvents,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
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

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const result = getPlayCampaignSafetyEvents(id);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
