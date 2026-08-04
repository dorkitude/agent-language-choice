import { requireSession } from "../../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import {
  createPlayDowntimeAllocation,
  getPlayDowntimeActivity,
  getPlayMemberByCharacterId,
  hasPlayDowntimeAllocation,
  PlayDowntimeAllocation,
} from "../../../../../../store.js";

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
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { activity_id?: unknown };

  const validActivityId = requireNonEmptyString(body.activity_id, "activity_id");
  if (validActivityId instanceof Response) return validActivityId;

  const username = session.user.username;
  if (username === campaign.owner) {
    return Response.json({ error: "the dm may not allocate downtime" }, { status: 403 });
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
      { error: `only ${currentOwner} may allocate downtime for character ${characterId}` },
      { status: 403 },
    );
  }

  const activity = getPlayDowntimeActivity(campaignId, validActivityId);
  if (!activity) {
    return Response.json(
      { error: `downtime activity ${validActivityId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (hasPlayDowntimeAllocation(campaignId, characterId, validActivityId)) {
    return Response.json(
      {
        error: `character ${characterId} already has an allocation for activity ${validActivityId}`,
      },
      { status: 409 },
    );
  }

  const allocation: PlayDowntimeAllocation = {
    campaign_id: campaignId,
    character_id: characterId,
    activity_id: validActivityId,
    cycles_completed: 0,
    completions: 0,
  };
  createPlayDowntimeAllocation(allocation);

  return Response.json(serializeAllocation(allocation), { status: 201 });
}
