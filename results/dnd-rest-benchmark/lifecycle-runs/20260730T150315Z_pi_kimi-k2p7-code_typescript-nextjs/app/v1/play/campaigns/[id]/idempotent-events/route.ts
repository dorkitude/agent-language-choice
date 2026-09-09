import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignIdempotentEvent,
  getPlayCampaign,
  getPlayCampaignIdempotentEvents,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import type { CreatePlayCampaignIdempotentEventInput } from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const idempotencyKey = req.headers.get("Idempotency-Key")?.trim();
  if (!idempotencyKey) {
    return badRequest();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.event_id) || !isNonEmptyString(b.value)) {
    return badRequest();
  }

  const input: CreatePlayCampaignIdempotentEventInput = {
    event_id: b.event_id,
    value: b.value,
    idempotency_key: idempotencyKey,
  };

  const result = createPlayCampaignIdempotentEvent(id, input);

  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  if (result.created) {
    return created(result.event);
  }
  return NextResponse.json(result.event);
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const events = getPlayCampaignIdempotentEvents(id);
  if (!events) {
    return notFound();
  }

  return ok(events);
}
