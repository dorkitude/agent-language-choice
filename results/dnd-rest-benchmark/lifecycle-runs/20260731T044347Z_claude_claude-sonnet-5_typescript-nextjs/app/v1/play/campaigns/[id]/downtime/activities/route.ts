import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import {
  createPlayDowntimeActivity,
  hasPlayDowntimeActivity,
  PlayDowntimeActivity,
} from "../../../../store.js";

function serializeActivity(activity: PlayDowntimeActivity) {
  return {
    activity_id: activity.activity_id,
    name: activity.name,
    cycles_required: activity.cycles_required,
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
    "only the campaign dm may create downtime activities",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    activity_id?: unknown;
    name?: unknown;
    cycles_required?: unknown;
  };

  const validActivityId = requireNonEmptyString(body.activity_id, "activity_id");
  if (validActivityId instanceof Response) return validActivityId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const cyclesRequired = body.cycles_required;
  if (
    typeof cyclesRequired !== "number" ||
    !Number.isInteger(cyclesRequired) ||
    cyclesRequired < 1 ||
    cyclesRequired > 10
  ) {
    return Response.json(
      { error: "cycles_required must be an integer from 1 through 10" },
      { status: 400 },
    );
  }

  if (hasPlayDowntimeActivity(campaignId, validActivityId)) {
    return Response.json(
      { error: `downtime activity ${validActivityId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const activity: PlayDowntimeActivity = {
    campaign_id: campaignId,
    activity_id: validActivityId,
    name: validName,
    cycles_required: cyclesRequired,
  };
  createPlayDowntimeActivity(activity);

  return Response.json(serializeActivity(activity), { status: 201 });
}
