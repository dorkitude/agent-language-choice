import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  getPlayQuest,
  PlayQuestRewards,
  updatePlayQuest,
  VALID_INVENTORY_ITEM_IDS,
} from "../../../../../store.js";

function parseRewardsBody(body: unknown): PlayQuestRewards | Response {
  const candidate = (body ?? {}) as { xp?: unknown; items?: unknown };

  if (
    typeof candidate.xp !== "number" ||
    !Number.isInteger(candidate.xp) ||
    candidate.xp < 0
  ) {
    return Response.json({ error: "xp must be a nonnegative integer" }, { status: 400 });
  }

  if (
    typeof candidate.items !== "object" ||
    candidate.items === null ||
    Array.isArray(candidate.items)
  ) {
    return Response.json({ error: "items must be an object" }, { status: 400 });
  }

  const items: Record<string, number> = {};
  for (const [itemId, quantity] of Object.entries(candidate.items as Record<string, unknown>)) {
    if (!(VALID_INVENTORY_ITEM_IDS as readonly string[]).includes(itemId)) {
      return Response.json({ error: `unknown catalog item ${itemId}` }, { status: 400 });
    }
    if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity <= 0) {
      return Response.json(
        { error: `items.${itemId} must be a positive integer` },
        { status: 400 },
      );
    }
    items[itemId] = quantity;
  }

  return { xp: candidate.xp, items };
}

export async function PUT(
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
    "only the campaign dm may configure quest rewards",
  );
  if (ownerCheck) return ownerCheck;

  const quest = getPlayQuest(campaignId, questId);
  if (!quest) {
    return Response.json(
      { error: `quest ${questId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (quest.state !== "locked" && quest.state !== "active") {
    return Response.json(
      { error: `cannot configure rewards for quest ${questId} in state ${quest.state}` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;

  const rewards = parseRewardsBody(parsed.body);
  if (rewards instanceof Response) return rewards;

  const updatedQuest = updatePlayQuest(campaignId, { ...quest, rewards });

  return Response.json(
    {
      quest_id: updatedQuest.quest_id,
      title: updatedQuest.title,
      depends_on: updatedQuest.depends_on,
      state: updatedQuest.state,
      rewards: updatedQuest.rewards,
    },
    { status: 200 },
  );
}
