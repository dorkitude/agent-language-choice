import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayWorldEvent,
  getPlayMemberForUser,
  hasPlayWorldEvent,
  listPlayWorldEvents,
  PlayWorldEvent,
} from "../../../store.js";

function serializeWorldEvent(event: PlayWorldEvent) {
  return {
    event_id: event.event_id,
    turn_number: event.turn_number,
    title: event.title,
    text: event.text,
    status: event.status,
    ...(event.resolution ? { resolution: event.resolution } : {}),
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
    "only the campaign dm may schedule world events",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    event_id?: unknown;
    turn_number?: unknown;
    title?: unknown;
    text?: unknown;
  };

  const validEventId = requireNonEmptyString(body.event_id, "event_id");
  if (validEventId instanceof Response) return validEventId;

  const validTitle = requireNonEmptyString(body.title, "title");
  if (validTitle instanceof Response) return validTitle;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  const currentTurn = campaign.turn_number ?? 0;
  const { turn_number: turnNumber } = body;
  if (
    typeof turnNumber !== "number" ||
    !Number.isInteger(turnNumber) ||
    turnNumber < currentTurn
  ) {
    return Response.json(
      { error: `turn_number must be an integer greater than or equal to ${currentTurn}` },
      { status: 400 },
    );
  }

  if (hasPlayWorldEvent(campaignId, validEventId)) {
    return Response.json(
      { error: `world event ${validEventId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const event: PlayWorldEvent = {
    event_id: validEventId,
    turn_number: turnNumber,
    title: validTitle,
    text: validText,
    status: "scheduled",
  };

  createPlayWorldEvent(campaignId, event);

  return Response.json(serializeWorldEvent(event), { status: 201 });
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

  const events = listPlayWorldEvents(campaignId);

  return Response.json({ events: events.map(serializeWorldEvent) }, { status: 200 });
}
