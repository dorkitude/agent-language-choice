import { requirePlayCampaign } from "../../../../../../../../http.js";
import { requireSession } from "../../../../../../../../../auth/session.js";
import {
  getPlayMemberByCharacterId,
  updatePlayMember,
  CONSUMABLE_ITEM_IDS,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../../../../../../store.js";

const CONSUME_EFFECTS: Record<string, { type: string; hp_restored: number }> = {
  "healing-potion": { type: "healing", hp_restored: 5 },
};

export async function POST(
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
      { error: "only the character's owner may consume inventory items" },
      { status: 403 },
    );
  }

  if (!(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)) {
    return Response.json({ error: "item_id must be a known catalog item" }, { status: 400 });
  }

  if (!(CONSUMABLE_ITEM_IDS as readonly string[]).includes(itemId)) {
    return Response.json({ error: `item ${itemId} is not consumable` }, { status: 400 });
  }

  const items = [...(member.inventory_items ?? [])];
  const existing = items.find((item) => item.item_id === itemId);
  const heldQuantity = existing?.quantity ?? 0;

  if (heldQuantity < 1) {
    return Response.json(
      { error: `character ${characterId} does not hold ${itemId}` },
      { status: 409 },
    );
  }

  const totalQuantity = heldQuantity - 1;
  const remainingItems = items.filter((item) => item.item_id !== itemId);
  if (totalQuantity > 0) {
    remainingItems.push({ item_id: itemId, quantity: totalQuantity });
  }

  updatePlayMember({ ...member, inventory_items: remainingItems });

  return Response.json(
    {
      character_id: characterId,
      item_id: itemId,
      quantity_consumed: 1,
      total_quantity: totalQuantity,
      effect: CONSUME_EFFECTS[itemId],
    },
    { status: 200 },
  );
}
