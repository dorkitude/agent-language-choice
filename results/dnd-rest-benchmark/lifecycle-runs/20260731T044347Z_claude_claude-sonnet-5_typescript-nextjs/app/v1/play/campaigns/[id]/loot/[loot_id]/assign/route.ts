import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  getPlayLoot,
  getPlayMemberByCharacterId,
  updatePlayLoot,
  updatePlayMember,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> },
) {
  const { id: campaignId, loot_id: lootId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  if (username !== campaign.owner) {
    return Response.json({ error: `only the campaign dm may assign loot` }, { status: 403 });
  }

  const loot = getPlayLoot(campaignId, lootId);
  if (!loot) {
    return Response.json(
      { error: `loot ${lootId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (loot.status !== "open") {
    return Response.json({ error: `loot ${lootId} is not open` }, { status: 409 });
  }

  const tally = new Map<string, number>();
  for (const vote of loot.votes) {
    tally.set(vote.recipient_character_id, (tally.get(vote.recipient_character_id) ?? 0) + 1);
  }

  let recipientId: string | undefined;
  let topVotes = 0;
  let tied = false;
  for (const [candidate, count] of tally) {
    if (count > topVotes) {
      topVotes = count;
      recipientId = candidate;
      tied = false;
    } else if (count === topVotes) {
      tied = true;
    }
  }

  if (!recipientId || tied) {
    return Response.json(
      { error: `loot ${lootId} has no unambiguous highest vote recipient` },
      { status: 409 },
    );
  }

  const recipient = getPlayMemberByCharacterId(campaignId, recipientId);
  if (!recipient) {
    return Response.json(
      { error: `character ${recipientId} not found in campaign ${campaignId}` },
      { status: 400 },
    );
  }

  const items = [...(recipient.inventory_items ?? [])];
  const existing = items.find((item) => item.item_id === loot.item_id);
  if (existing) {
    existing.quantity += loot.quantity;
  } else {
    items.push({ item_id: loot.item_id, quantity: loot.quantity });
  }
  updatePlayMember({ ...recipient, inventory_items: items });

  const updated = updatePlayLoot({
    ...loot,
    status: "assigned",
    recipient_character_id: recipientId,
  });

  return Response.json(
    {
      loot_id: updated.loot_id,
      recipient_character_id: recipientId,
      item_id: updated.item_id,
      quantity: updated.quantity,
      votes: topVotes,
      status: updated.status,
    },
    { status: 200 },
  );
}
