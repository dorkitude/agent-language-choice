import { requireSession } from "../../../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../../../http.js";
import {
  getPlayDowntimeAllocation,
  hasPlayMemberForUser,
  PlayDowntimeAllocation,
} from "../../../../../../../store.js";

function serializeAllocation(allocation: PlayDowntimeAllocation) {
  return {
    character_id: allocation.character_id,
    activity_id: allocation.activity_id,
    cycles_completed: allocation.cycles_completed,
    completions: allocation.completions,
  };
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string; activity_id: string }> },
) {
  const { id: campaignId, char_id: characterId, activity_id: activityId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
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

  return Response.json(serializeAllocation(allocation), { status: 200 });
}
