import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayWorldEvent, updatePlayWorldEvent } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; event_id: string }> },
) {
  const { id: campaignId, event_id: eventId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may resolve world events",
  );
  if (ownerCheck) return ownerCheck;

  const event = getPlayWorldEvent(campaignId, eventId);
  if (!event) {
    return Response.json(
      { error: `world event ${eventId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { text?: unknown };

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  if (event.status === "resolved") {
    return Response.json(
      { error: `world event ${eventId} is already resolved` },
      { status: 409 },
    );
  }

  const currentTurn = campaign.turn_number ?? 0;
  if (currentTurn !== event.turn_number) {
    return Response.json(
      {
        error: `world event ${eventId} can only be resolved on turn ${event.turn_number}, current turn is ${currentTurn}`,
      },
      { status: 409 },
    );
  }

  const resolvedEvent = {
    ...event,
    status: "resolved" as const,
    resolution: {
      turn_number: event.turn_number,
      text: validText,
    },
  };

  updatePlayWorldEvent(campaignId, resolvedEvent);

  return Response.json(
    {
      event_id: resolvedEvent.event_id,
      turn_number: resolvedEvent.turn_number,
      title: resolvedEvent.title,
      text: resolvedEvent.text,
      status: resolvedEvent.status,
      resolution: resolvedEvent.resolution,
    },
    { status: 201 },
  );
}
