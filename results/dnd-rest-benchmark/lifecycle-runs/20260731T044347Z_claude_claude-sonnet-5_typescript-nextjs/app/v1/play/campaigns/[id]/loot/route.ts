import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import { createPlayLoot, hasPlayLoot, VALID_INVENTORY_ITEM_IDS } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  if (username !== campaign.owner) {
    return Response.json({ error: `only the campaign dm may create loot` }, { status: 403 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { loot_id?: unknown; item_id?: unknown; quantity?: unknown };

  const validLootId = requireNonEmptyString(body.loot_id, "loot_id");
  if (validLootId instanceof Response) return validLootId;

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

  if (hasPlayLoot(campaignId, validLootId)) {
    return Response.json(
      { error: `loot ${validLootId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const loot = createPlayLoot({
    campaign_id: campaignId,
    loot_id: validLootId,
    item_id: itemId,
    quantity,
    status: "open",
    votes: [],
  });

  return Response.json(
    { loot_id: loot.loot_id, item_id: loot.item_id, quantity: loot.quantity, status: loot.status },
    { status: 201 },
  );
}
