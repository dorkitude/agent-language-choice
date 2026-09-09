import { requireBearerAuth } from "../../../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../../../lib/http.js";
import {
  consumeCharacterInventoryItem,
  getCharacterOwner,
  getPlayCampaign,
} from "../../../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string; item_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id: character_id, item_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const ownerRecord = getCharacterOwner(id, character_id);
  if (!ownerRecord) {
    return notFound();
  }

  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const result = consumeCharacterInventoryItem(id, character_id, item_id);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return ok(result);
}
