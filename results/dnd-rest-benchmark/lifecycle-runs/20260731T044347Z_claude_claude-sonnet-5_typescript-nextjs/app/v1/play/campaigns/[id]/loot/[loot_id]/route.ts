import { requireSession } from "../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../http.js";
import { getPlayLoot, hasPlayMemberForUser } from "../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> },
) {
  const { id: campaignId, loot_id: lootId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const loot = getPlayLoot(campaignId, lootId);
  if (!loot) {
    return Response.json(
      { error: `loot ${lootId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const votes: Record<string, number> = {};
  for (const vote of loot.votes) {
    votes[vote.recipient_character_id] = (votes[vote.recipient_character_id] ?? 0) + 1;
  }

  return Response.json(
    {
      loot_id: loot.loot_id,
      item_id: loot.item_id,
      quantity: loot.quantity,
      status: loot.status,
      recipient_character_id: loot.recipient_character_id ?? null,
      votes,
    },
    { status: 200 },
  );
}
