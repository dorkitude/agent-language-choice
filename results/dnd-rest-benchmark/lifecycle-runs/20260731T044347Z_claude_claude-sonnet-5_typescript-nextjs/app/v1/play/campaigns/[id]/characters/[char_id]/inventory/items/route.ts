import { parseJsonBody } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import { requireSession } from "../../../../../../../auth/session.js";
import {
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  updatePlayMember,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const items = [...(member.inventory_items ?? [])]
    .sort((a, b) => (a.item_id < b.item_id ? -1 : a.item_id > b.item_id ? 1 : 0))
    .map((item) => ({ item_id: item.item_id, quantity: item.quantity }));

  return Response.json({ character_id: characterId, items }, { status: 200 });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

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
      { error: "only the character's owner may add inventory items" },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { item_id?: unknown; quantity?: unknown };

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

  const items = [...(member.inventory_items ?? [])];
  const existing = items.find((item) => item.item_id === itemId);
  const totalQuantity = (existing?.quantity ?? 0) + quantity;

  if (existing) {
    existing.quantity = totalQuantity;
  } else {
    items.push({ item_id: itemId, quantity: totalQuantity });
  }

  updatePlayMember({ ...member, inventory_items: items });

  return Response.json(
    { character_id: characterId, item_id: itemId, quantity, total_quantity: totalQuantity },
    { status: 201 },
  );
}
