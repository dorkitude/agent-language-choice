import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayIdempotentEvent,
  getNextPlayIdempotentSequence,
  getPlayIdempotentEventByKey,
  getPlayMemberForUser,
  hasPlayIdempotentEventId,
  listPlayIdempotentEvents,
  PlayIdempotentEvent,
} from "../../../store.js";

function serializeIdempotentEvent(event: PlayIdempotentEvent) {
  return {
    event_id: event.event_id,
    value: event.value,
    sequence: event.sequence,
    idempotency_key: event.idempotency_key,
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
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const idempotencyKey = (request.headers.get("Idempotency-Key") ?? "").trim();
  if (idempotencyKey.length === 0) {
    return Response.json(
      { error: "Idempotency-Key header must be a non-empty string" },
      { status: 400 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { event_id?: unknown; value?: unknown };

  const validEventId = requireNonEmptyString(body.event_id, "event_id");
  if (validEventId instanceof Response) return validEventId;

  const validValue = requireNonEmptyString(body.value, "value");
  if (validValue instanceof Response) return validValue;

  const existingForKey = getPlayIdempotentEventByKey(campaignId, idempotencyKey);
  if (existingForKey) {
    if (existingForKey.event_id === validEventId && existingForKey.value === validValue) {
      return Response.json(serializeIdempotentEvent(existingForKey), { status: 200 });
    }
    return Response.json(
      { error: `idempotency key ${idempotencyKey} was already used with a different request` },
      { status: 409 },
    );
  }

  if (hasPlayIdempotentEventId(campaignId, validEventId)) {
    return Response.json(
      { error: `event_id ${validEventId} already used in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const event: PlayIdempotentEvent = {
    sequence: getNextPlayIdempotentSequence(campaignId),
    event_id: validEventId,
    value: validValue,
    idempotency_key: idempotencyKey,
  };

  createPlayIdempotentEvent(campaignId, event);

  return Response.json(serializeIdempotentEvent(event), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const events = listPlayIdempotentEvents(campaignId);

  return Response.json(
    { events: events.map(serializeIdempotentEvent) },
    { status: 200 },
  );
}
