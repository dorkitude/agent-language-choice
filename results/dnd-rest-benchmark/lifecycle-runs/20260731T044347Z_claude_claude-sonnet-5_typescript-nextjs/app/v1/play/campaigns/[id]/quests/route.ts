import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayQuest,
  getPlayMemberForUser,
  hasPlayQuest,
  listPlayQuests,
  PlayQuest,
} from "../../../store.js";

function serializeQuest(quest: PlayQuest) {
  return {
    quest_id: quest.quest_id,
    title: quest.title,
    depends_on: quest.depends_on,
    state: quest.state,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create quests",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    quest_id?: unknown;
    title?: unknown;
    depends_on?: unknown;
  };

  const validQuestId = requireNonEmptyString(body.quest_id, "quest_id");
  if (validQuestId instanceof Response) return validQuestId;

  const validTitle = requireNonEmptyString(body.title, "title");
  if (validTitle instanceof Response) return validTitle;

  const dependsOn = body.depends_on;
  if (
    !Array.isArray(dependsOn) ||
    !dependsOn.every((entry) => typeof entry === "string" && entry.length > 0)
  ) {
    return Response.json({ error: "depends_on must be an array of quest ids" }, { status: 400 });
  }

  const uniqueDependsOn = new Set(dependsOn);
  if (uniqueDependsOn.size !== dependsOn.length) {
    return Response.json({ error: "depends_on must not contain duplicate quest ids" }, { status: 400 });
  }

  if (dependsOn.includes(validQuestId)) {
    return Response.json({ error: "depends_on must not include the quest's own id" }, { status: 400 });
  }

  for (const dependencyId of dependsOn) {
    if (!hasPlayQuest(campaignId, dependencyId)) {
      return Response.json(
        { error: `dependency quest ${dependencyId} not found in campaign ${campaignId}` },
        { status: 400 },
      );
    }
  }

  if (hasPlayQuest(campaignId, validQuestId)) {
    return Response.json(
      { error: `quest ${validQuestId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const quest: PlayQuest = {
    quest_id: validQuestId,
    title: validTitle,
    depends_on: dependsOn,
    state: "locked",
  };

  createPlayQuest(campaignId, quest);

  return Response.json(serializeQuest(quest), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  const isMember = isDm || member !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const quests = listPlayQuests(campaignId);

  return Response.json({ quests: quests.map(serializeQuest) }, { status: 200 });
}
