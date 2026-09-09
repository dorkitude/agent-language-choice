import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  conflict,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../lib/http.js";
import {
  assignLoot,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, loot_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const result = assignLoot(id, loot_id);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "closed" || result === "tied") {
    return conflict();
  }

  return ok({
    loot_id: result.loot_id,
    recipient_character_id: result.recipient_character_id,
    item_id: result.item_id,
    quantity: result.quantity,
    votes: result.votes,
    status: result.status,
  });
}
