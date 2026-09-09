import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createLoot,
  getPlayCampaign,
  isValidInventoryItemId,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.loot_id !== "string" ||
    b.loot_id.length === 0 ||
    typeof b.item_id !== "string" ||
    b.item_id.length === 0 ||
    !Number.isInteger(b.quantity) ||
    (b.quantity as number) < 1
  ) {
    return badRequest();
  }

  if (!isValidInventoryItemId(b.item_id)) {
    return badRequest();
  }

  const result = createLoot(id, b.loot_id, b.item_id, b.quantity as number);
  if (!result) {
    return conflict();
  }

  return created({
    loot_id: result.loot_id,
    item_id: result.item_id,
    quantity: result.quantity,
    status: result.status,
  });
}
