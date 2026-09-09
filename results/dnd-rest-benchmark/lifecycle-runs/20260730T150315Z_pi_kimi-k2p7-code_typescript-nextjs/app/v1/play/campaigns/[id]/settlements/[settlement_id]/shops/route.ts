import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
} from "../../../../../../../lib/http.js";
import {
  createShop,
  getPlayCampaign,
  getSettlement,
  normalizeShopStock,
} from "../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, settlement_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const settlement = getSettlement(id, settlement_id);
  if (!settlement) {
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
    !isNonEmptyString(body.shop_id) ||
    !isNonEmptyString(body.name) ||
    !Number.isInteger(body.buy_price) ||
    (body.buy_price as number) <= 0 ||
    !Number.isInteger(body.sell_price) ||
    (body.sell_price as number) < 0
  ) {
    return badRequest();
  }

  const stock = normalizeShopStock(body.stock);
  if (stock === null) {
    return badRequest();
  }

  const result = createShop(id, settlement_id, {
    shop_id: body.shop_id as string,
    name: body.name as string,
    stock,
    buy_price: body.buy_price as number,
    sell_price: body.sell_price as number,
  });

  if (result === "bad_request") {
    return badRequest();
  }
  if (result === null) {
    return conflict();
  }

  return created(result);
}
