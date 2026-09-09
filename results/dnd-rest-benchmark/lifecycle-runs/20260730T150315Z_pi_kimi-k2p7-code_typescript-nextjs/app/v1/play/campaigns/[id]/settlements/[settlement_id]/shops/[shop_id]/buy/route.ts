import { requireBearerAuth } from "../../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../../lib/http.js";
import {
  buyFromShop,
  getCharacterOwner,
  getPlayCampaign,
  isValidInventoryItemId,
} from "../../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string; shop_id: string }> }
) {
  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  const { id, settlement_id, shop_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return badRequest("Invalid JSON");
  }
  if (typeof body !== "object" || body === null) {
    return badRequest("Bad request");
  }

  if (
    typeof body.character_id !== "string" ||
    body.character_id.length === 0 ||
    typeof body.item_id !== "string" ||
    !isValidInventoryItemId(body.item_id) ||
    !Number.isInteger(body.quantity) ||
    (body.quantity as number) <= 0
  ) {
    return badRequest();
  }

  const characterId = body.character_id as string;
  const itemId = body.item_id as string;
  const quantity = body.quantity as number;

  const ownerRecord = getCharacterOwner(id, characterId);
  if (!ownerRecord) {
    return notFound();
  }
  if (!ownerRecord.owner || ownerRecord.owner !== auth.user.username) {
    return forbidden();
  }

  const result = buyFromShop(id, settlement_id, shop_id, characterId, itemId, quantity);

  if (result === "not_found") {
    return notFound();
  }
  if (result === "invalid") {
    return badRequest();
  }
  if (result === "insufficient") {
    return conflict();
  }

  return ok(result);
}
