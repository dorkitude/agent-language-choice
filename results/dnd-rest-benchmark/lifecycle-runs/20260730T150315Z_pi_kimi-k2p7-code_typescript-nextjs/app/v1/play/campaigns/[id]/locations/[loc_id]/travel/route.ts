import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../../lib/http.js";
import {
  getOutboundConnections,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; loc_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, loc_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const destinations = getOutboundConnections(id, loc_id);
  if (destinations === null) {
    return notFound();
  }

  return ok({ destinations });
}
