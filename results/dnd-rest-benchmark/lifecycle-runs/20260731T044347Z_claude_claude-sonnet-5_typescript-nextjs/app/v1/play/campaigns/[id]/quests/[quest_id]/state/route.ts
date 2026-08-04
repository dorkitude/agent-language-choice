import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayQuest, PlayQuestState, updatePlayQuest } from "../../../../../store.js";

const VALID_STATES: PlayQuestState[] = ["active", "completed"];

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
    "only the campaign dm may change quest state",
  );
  if (ownerCheck) return ownerCheck;

  const quest = getPlayQuest(campaignId, questId);
  if (!quest) {
    return Response.json(
      { error: `quest ${questId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { state?: unknown };

  if (typeof body.state !== "string" || !VALID_STATES.includes(body.state as PlayQuestState)) {
    return Response.json({ error: "state must be exactly active or completed" }, { status: 400 });
  }
  const requestedState = body.state as PlayQuestState;

  if (requestedState === "active") {
    if (quest.state !== "locked") {
      return Response.json(
        { error: `cannot transition quest ${questId} from ${quest.state} to active` },
        { status: 409 },
      );
    }
    const unmetDependency = quest.depends_on.find((dependencyId: string) => {
      const dependency = getPlayQuest(campaignId, dependencyId);
      return dependency?.state !== "completed";
    });
    if (unmetDependency) {
      return Response.json(
        { error: `quest ${questId} has incomplete dependency ${unmetDependency}` },
        { status: 409 },
      );
    }
  } else {
    if (quest.state !== "active") {
      return Response.json(
        { error: `cannot transition quest ${questId} from ${quest.state} to completed` },
        { status: 409 },
      );
    }
  }

  const updatedQuest = updatePlayQuest(campaignId, { ...quest, state: requestedState });

  return Response.json(
    {
      quest_id: updatedQuest.quest_id,
      title: updatedQuest.title,
      depends_on: updatedQuest.depends_on,
      state: updatedQuest.state,
      ...(updatedQuest.rewards ? { rewards: updatedQuest.rewards } : {}),
    },
    { status: 200 },
  );
}
