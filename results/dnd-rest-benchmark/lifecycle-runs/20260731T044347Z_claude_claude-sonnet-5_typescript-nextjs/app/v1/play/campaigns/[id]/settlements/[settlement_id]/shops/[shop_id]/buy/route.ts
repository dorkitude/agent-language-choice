import { requireSession } from "../../../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../../http.js";
import {
  getPlayMemberByCharacterId,
  getPlayShop,
  getPlaySettlement,
  STARTING_GOLD,
  updatePlayMember,
  updatePlayShop,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string; shop_id: string }> },
) {
  const { id: campaignId, settlement_id: settlementId, shop_id: shopId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    return Response.json(
      { error: `settlement ${settlementId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const shop = getPlayShop(campaignId, settlementId, shopId);
  if (!shop) {
    return Response.json(
      { error: `shop ${shopId} not found in settlement ${settlementId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { character_id?: unknown; item_id?: unknown; quantity?: unknown };

  const characterId = body.character_id;
  if (typeof characterId !== "string" || characterId.length === 0) {
    return Response.json({ error: "character_id must be a non-empty string" }, { status: 400 });
  }

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const username = session.user.username;
  if (username === campaign.owner) {
    return Response.json({ error: "the dm may not buy from shops" }, { status: 403 });
  }

  const currentOwner = member.owner ?? member.username;
  if (username !== currentOwner) {
    return Response.json(
      { error: `only ${currentOwner} may buy for character ${characterId}` },
      { status: 403 },
    );
  }

  const itemId = body.item_id;
  if (
    typeof itemId !== "string" ||
    !(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)
  ) {
    return Response.json({ error: "item_id must be a known catalog item" }, { status: 400 });
  }

  const quantity = body.quantity;
  if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
    return Response.json({ error: "quantity must be a positive integer" }, { status: 400 });
  }

  const availableStock = shop.stock[itemId] ?? 0;
  if (availableStock < quantity) {
    return Response.json(
      { error: `shop ${shopId} does not have enough ${itemId} in stock` },
      { status: 409 },
    );
  }

  const cost = shop.buy_price * quantity;
  const currentGold = member.gold ?? STARTING_GOLD;
  if (currentGold < cost) {
    return Response.json(
      { error: `character ${characterId} has insufficient gold` },
      { status: 409 },
    );
  }

  const remainingStock = availableStock - quantity;
  updatePlayShop({ ...shop, stock: { ...shop.stock, [itemId]: remainingStock } });

  const items = [...(member.inventory_items ?? [])];
  const existing = items.find((item) => item.item_id === itemId);
  if (existing) {
    existing.quantity += quantity;
  } else {
    items.push({ item_id: itemId, quantity });
  }

  const newGold = currentGold - cost;
  updatePlayMember({ ...member, gold: newGold, inventory_items: items });

  return Response.json(
    {
      character_id: characterId,
      item_id: itemId,
      quantity,
      gold: newGold,
      stock: remainingStock,
    },
    { status: 200 },
  );
}
