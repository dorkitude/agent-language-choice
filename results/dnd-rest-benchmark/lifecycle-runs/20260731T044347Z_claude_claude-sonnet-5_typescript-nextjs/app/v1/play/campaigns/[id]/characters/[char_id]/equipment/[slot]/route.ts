import { parseJsonBody } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import { requireSession } from "../../../../../../../auth/session.js";
import {
  EQUIPMENT_ITEM_SLOTS,
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  PlayEquipmentSlot,
  updatePlayMember,
  VALID_EQUIPMENT_SLOTS,
} from "../../../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string; slot: string }> },
) {
  const { id: campaignId, char_id: characterId, slot } = await params;

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

  if (!(VALID_EQUIPMENT_SLOTS as readonly string[]).includes(slot)) {
    return Response.json({ error: "slot must be one of armor, accessory" }, { status: 400 });
  }

  const equippedItemId = member.equipment?.[slot as PlayEquipmentSlot] ?? "";
  const attuned = equippedItemId !== "" && member.attuned_item_id === equippedItemId;

  return Response.json(
    { character_id: characterId, slot, item_id: equippedItemId, attuned },
    { status: 200 },
  );
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string; slot: string }> },
) {
  const { id: campaignId, char_id: characterId, slot } = await params;

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
      { error: "only the character's owner may equip items" },
      { status: 403 },
    );
  }

  if (!(VALID_EQUIPMENT_SLOTS as readonly string[]).includes(slot)) {
    return Response.json({ error: "slot must be one of armor, accessory" }, { status: 400 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { item_id?: unknown };

  const itemId = body.item_id;
  if (typeof itemId !== "string" || !(itemId in EQUIPMENT_ITEM_SLOTS)) {
    return Response.json({ error: "item_id must be a known equippable item" }, { status: 400 });
  }

  if (EQUIPMENT_ITEM_SLOTS[itemId] !== slot) {
    return Response.json({ error: `${itemId} cannot be equipped in slot ${slot}` }, { status: 400 });
  }

  const held = (member.inventory_items ?? []).find((item) => item.item_id === itemId);
  if (!held || held.quantity < 1) {
    return Response.json(
      { error: `character ${characterId} does not hold ${itemId}` },
      { status: 400 },
    );
  }

  const equipment = { ...(member.equipment ?? {}), [slot as PlayEquipmentSlot]: itemId };
  updatePlayMember({ ...member, equipment });

  return Response.json(
    { character_id: characterId, slot, item_id: itemId, attuned: false },
    { status: 200 },
  );
}
