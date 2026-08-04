import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  transferCharacter,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
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
  if (!isMember) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.new_owner !== "string") {
    return badRequest();
  }

  const result = transferCharacter(id, char_id, b.new_owner, auth.user.username);
  if (result === null) {
    return notFound();
  }
  if (result === "not_owner") {
    return forbidden();
  }
  if (result === "not_member") {
    return badRequest();
  }

  return ok({
    character_id: result.character_id,
    owner: result.owner,
  });
}
