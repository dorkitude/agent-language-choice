import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  recordLootVote,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> }
) {
  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  const { id, loot_id } = await params;

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
  if (
    typeof b.recipient_character_id !== "string" ||
    b.recipient_character_id.length === 0
  ) {
    return badRequest();
  }

  const result = recordLootVote(
    id,
    loot_id,
    auth.user.username,
    b.recipient_character_id
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "invalid") {
    return badRequest();
  }

  return created({
    loot_id: result.loot_id,
    voter: result.voter,
    recipient_character_id: result.recipient_character_id,
    votes_for_recipient: result.votes_for_recipient,
  });
}
