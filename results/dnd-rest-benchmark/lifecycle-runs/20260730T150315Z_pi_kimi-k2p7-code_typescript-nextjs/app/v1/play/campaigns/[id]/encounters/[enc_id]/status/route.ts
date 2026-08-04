import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignEncounterStatus,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, enc_id } = await params;

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

  const status = getPlayCampaignEncounterStatus(id, enc_id);
  if (!status) {
    return notFound();
  }

  return ok({
    round: status.round,
    turn_index: status.turn_index,
    active: status.active,
    order: status.order,
    conditions: status.conditions,
  });
}
