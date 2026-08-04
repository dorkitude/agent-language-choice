import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayProjectionEvent,
  getNextPlayProjectionSequence,
  getPlayMemberForUser,
  hasPlayProjectionEventId,
  PlayProjectionEvent,
} from "../../../store.js";

function serializeProjectionEvent(event: PlayProjectionEvent) {
  if (event.kind === "increment-danger") {
    return { sequence: event.sequence, event_id: event.event_id, kind: event.kind };
  }
  return {
    sequence: event.sequence,
    event_id: event.event_id,
    kind: event.kind,
    value: event.value,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    if (isDm) {
      return Response.json(
        { error: "the campaign DM may not append projection events" },
        { status: 403 },
      );
    }
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { event_id?: unknown; kind?: unknown; value?: unknown };

  const validEventId = requireNonEmptyString(body.event_id, "event_id");
  if (validEventId instanceof Response) return validEventId;

  if (body.kind !== "set-story" && body.kind !== "increment-danger") {
    return Response.json(
      { error: "kind must be one of: set-story, increment-danger" },
      { status: 400 },
    );
  }
  const kind = body.kind;

  if (kind === "set-story") {
    const validValue = requireNonEmptyString(body.value, "value");
    if (validValue instanceof Response) return validValue;
  } else if (body.value !== undefined) {
    return Response.json(
      { error: "value must be omitted for increment-danger events" },
      { status: 400 },
    );
  }

  if (hasPlayProjectionEventId(campaignId, validEventId)) {
    return Response.json(
      { error: `event_id ${validEventId} already used in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const event: PlayProjectionEvent = {
    sequence: getNextPlayProjectionSequence(campaignId),
    event_id: validEventId,
    kind,
    ...(kind === "set-story" ? { value: body.value as string } : {}),
  };

  createPlayProjectionEvent(campaignId, event);

  return Response.json(serializeProjectionEvent(event), { status: 201 });
}
