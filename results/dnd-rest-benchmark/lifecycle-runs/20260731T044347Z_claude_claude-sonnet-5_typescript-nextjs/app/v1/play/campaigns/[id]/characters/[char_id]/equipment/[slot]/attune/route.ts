import { requirePlayCampaign } from "../../../../../../../http.js";
import { requireSession } from "../../../../../../../../auth/session.js";
import {
  ATTUNABLE_ITEM_IDS,
  getPlayMemberByCharacterId,
  MAX_ATTUNEMENTS,
  PlayEquipmentSlot,
  updatePlayMember,
  VALID_EQUIPMENT_SLOTS,
} from "../../../../../../../store.js";

export async function POST(
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
      { error: "only the character's owner may attune items" },
      { status: 403 },
    );
  }

  if (!(VALID_EQUIPMENT_SLOTS as readonly string[]).includes(slot)) {
    return Response.json({ error: "slot must be one of armor, accessory" }, { status: 400 });
  }

  const equippedItemId = member.equipment?.[slot as PlayEquipmentSlot];
  if (!equippedItemId || !(ATTUNABLE_ITEM_IDS as readonly string[]).includes(equippedItemId)) {
    return Response.json(
      { error: `slot ${slot} does not contain an attunable item` },
      { status: 400 },
    );
  }

  if (member.attuned_item_id) {
    return Response.json(
      { error: `character ${characterId} has already reached the attunement limit` },
      { status: 409 },
    );
  }

  updatePlayMember({ ...member, attuned_item_id: equippedItemId });

  return Response.json(
    {
      character_id: characterId,
      slot,
      item_id: equippedItemId,
      attuned: true,
      attunement_count: 1,
      max_attunements: MAX_ATTUNEMENTS,
    },
    { status: 200 },
  );
}
