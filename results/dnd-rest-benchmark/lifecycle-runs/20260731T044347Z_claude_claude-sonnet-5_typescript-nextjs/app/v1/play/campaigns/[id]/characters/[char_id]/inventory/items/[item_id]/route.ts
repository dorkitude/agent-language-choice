import { parseJsonBody } from "../../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../../http.js";
import { requireSession } from "../../../../../../../../auth/session.js";
import {
  getPlayMemberByCharacterId,
  updatePlayMember,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../../../../../store.js";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string; item_id: string }> },
) {
  const { id: campaignId, char_id: characterId, item_id: itemId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const currentOwner = member.owner ?? member.username;
  if (session.user.username !== currentOwner) {
    return Response.json(
      { error: "only the character's owner may remove inventory items" },
      { status: 403 },
    );
  }

  if (!(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)) {
    return Response.json({ error: "item_id must be a known catalog item" }, { status: 400 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { quantity?: unknown };

  const quantity = body.quantity;
  if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
    return Response.json({ error: "quantity must be a positive integer" }, { status: 400 });
  }

  const items = [...(member.inventory_items ?? [])];
  const existing = items.find((item) => item.item_id === itemId);
  const heldQuantity = existing?.quantity ?? 0;

  if (quantity > heldQuantity) {
    return Response.json(
      { error: `character ${characterId} does not hold ${quantity} of ${itemId}` },
      { status: 409 },
    );
  }

  const totalQuantity = heldQuantity - quantity;
  const remainingItems = items.filter((item) => item.item_id !== itemId);
  if (totalQuantity > 0) {
    remainingItems.push({ item_id: itemId, quantity: totalQuantity });
  }

  updatePlayMember({ ...member, inventory_items: remainingItems });

  return Response.json(
    { character_id: characterId, item_id: itemId, quantity, total_quantity: totalQuantity },
    { status: 200 },
  );
}
