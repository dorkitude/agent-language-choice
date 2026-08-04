import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../lib/http.js";
import {
  getCurrentScene,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../lib/storage.js";

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
  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const scene = getCurrentScene(id);
  if (!scene) {
    return notFound();
  }

  return ok(scene);
}
