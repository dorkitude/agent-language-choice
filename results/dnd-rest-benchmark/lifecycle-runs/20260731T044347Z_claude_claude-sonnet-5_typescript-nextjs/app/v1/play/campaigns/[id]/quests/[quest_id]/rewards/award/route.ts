import { requireSession } from "../../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../../http.js";
import {
  getPlayQuest,
  grantPlayCharacterRewards,
  listPlayMembers,
  updatePlayMember,
  updatePlayQuest,
} from "../../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> },
) {
  const { id: campaignId, quest_id: questId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may award quest rewards",
  );
  if (ownerCheck) return ownerCheck;

  const quest = getPlayQuest(campaignId, questId);
  if (!quest) {
    return Response.json(
      { error: `quest ${questId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (quest.state !== "completed" || !quest.rewards) {
    return Response.json(
      { error: `quest ${questId} is not ready to award rewards` },
      { status: 409 },
    );
  }

  if (quest.rewards_awarded) {
    return Response.json(
      { error: `rewards already awarded for quest ${questId}` },
      { status: 409 },
    );
  }

  const rewards = quest.rewards;

  for (const member of listPlayMembers(campaignId)) {
    grantPlayCharacterRewards(campaignId, member.character_id, {
      xp: rewards.xp,
      items: rewards.items,
    });

    const inventoryItems = [...(member.inventory_items ?? [])];
    for (const [itemId, quantity] of Object.entries(rewards.items)) {
      const existing = inventoryItems.find((item) => item.item_id === itemId);
      if (existing) {
        existing.quantity += quantity;
      } else {
        inventoryItems.push({ item_id: itemId, quantity });
      }
    }
    updatePlayMember({ ...member, inventory_items: inventoryItems });
  }

  updatePlayQuest(campaignId, { ...quest, rewards_awarded: true });

  return Response.json(
    {
      quest_id: quest.quest_id,
      awarded: true,
      xp: rewards.xp,
      items: rewards.items,
    },
    { status: 201 },
  );
}
