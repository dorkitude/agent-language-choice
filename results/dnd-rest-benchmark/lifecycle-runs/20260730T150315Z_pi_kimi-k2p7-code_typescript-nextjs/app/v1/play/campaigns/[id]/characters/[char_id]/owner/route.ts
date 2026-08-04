import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../../../lib/http.js";
import {
  getCharacterOwner,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

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

  const ownerRecord = getCharacterOwner(id, char_id);
  if (!ownerRecord) {
    return notFound();
  }

  return ok({
    character_id: ownerRecord.character_id,
    owner: ownerRecord.owner,
  });
}
