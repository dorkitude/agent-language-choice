import { requireSession } from "../../../../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../../../../http.js";
import {
  getPlayDowntimeActivity,
  getPlayDowntimeAllocation,
  getPlayMemberByCharacterId,
  PlayDowntimeAllocation,
  updatePlayDowntimeAllocation,
} from "../../../../../../../../store.js";

function serializeAllocation(allocation: PlayDowntimeAllocation) {
  return {
    character_id: allocation.character_id,
    activity_id: allocation.activity_id,
    cycles_completed: allocation.cycles_completed,
    completions: allocation.completions,
  };
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string; activity_id: string }> },
) {
  const { id: campaignId, char_id: characterId, activity_id: activityId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  if (username === campaign.owner) {
    return Response.json({ error: "the dm may not progress downtime" }, { status: 403 });
  }

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const currentOwner = member.owner ?? member.username;
  if (username !== currentOwner) {
    return Response.json(
      { error: `only ${currentOwner} may progress downtime for character ${characterId}` },
      { status: 403 },
    );
  }

  const activity = getPlayDowntimeActivity(campaignId, activityId);
  if (!activity) {
    return Response.json(
      { error: `downtime activity ${activityId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const allocation = getPlayDowntimeAllocation(campaignId, characterId, activityId);
  if (!allocation) {
    return Response.json(
      {
        error: `character ${characterId} has no allocation for activity ${activityId}`,
      },
      { status: 404 },
    );
  }

  let cyclesCompleted = allocation.cycles_completed + 1;
  let completions = allocation.completions;
  if (cyclesCompleted >= activity.cycles_required) {
    cyclesCompleted = 0;
    completions += 1;
  }

  const updated: PlayDowntimeAllocation = {
    ...allocation,
    cycles_completed: cyclesCompleted,
    completions,
  };
  updatePlayDowntimeAllocation(updated);

  return Response.json(serializeAllocation(updated), { status: 200 });
}
