import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { createPlayShop, getPlaySettlement, hasPlayShop, PlayShop } from "../../../../../store.js";
import { serializeShop, validatePrice, validateStock } from "./shared.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> },
) {
  const { id: campaignId, settlement_id: settlementId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create shops",
  );
  if (ownerCheck) return ownerCheck;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    return Response.json(
      { error: `settlement ${settlementId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    shop_id?: unknown;
    name?: unknown;
    stock?: unknown;
    buy_price?: unknown;
    sell_price?: unknown;
  };

  const validShopId = requireNonEmptyString(body.shop_id, "shop_id");
  if (validShopId instanceof Response) return validShopId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const validStock = validateStock(body.stock);
  if (validStock instanceof Response) return validStock;

  const validBuyPrice = validatePrice(body.buy_price, "buy_price", false);
  if (validBuyPrice instanceof Response) return validBuyPrice;

  const validSellPrice = validatePrice(body.sell_price, "sell_price", true);
  if (validSellPrice instanceof Response) return validSellPrice;

  if (hasPlayShop(campaignId, settlementId, validShopId)) {
    return Response.json(
      { error: `shop ${validShopId} already exists in settlement ${settlementId}` },
      { status: 409 },
    );
  }

  const shop: PlayShop = {
    campaign_id: campaignId,
    settlement_id: settlementId,
    shop_id: validShopId,
    name: validName,
    stock: validStock,
    buy_price: validBuyPrice,
    sell_price: validSellPrice,
  };

  createPlayShop(shop);

  return Response.json(serializeShop(shop), { status: 201 });
}
