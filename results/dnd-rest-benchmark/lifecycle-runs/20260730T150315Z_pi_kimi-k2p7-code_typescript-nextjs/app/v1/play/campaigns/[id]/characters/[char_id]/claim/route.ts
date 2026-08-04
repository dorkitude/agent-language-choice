import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  conflict,
  created,
  forbidden,
  notFound,
} from "../../../../../../../lib/http.js";
import {
  claimCharacter,
  getPlayCampaign,
  getPlayCampaignMembers,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  if (!isMember) {
    return forbidden();
  }

  const result = claimCharacter(id, char_id, auth.user.username);
  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created({
    character_id: result.character_id,
    owner: result.owner,
  });
}
