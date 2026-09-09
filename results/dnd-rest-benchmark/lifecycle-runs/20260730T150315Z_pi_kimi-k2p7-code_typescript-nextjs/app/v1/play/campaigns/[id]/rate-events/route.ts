import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignRateEvent,
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignRateEvents,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

const RATE_EVENT_LIMIT = 2;

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

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.event_id)) {
    return badRequest();
  }

  const result = createPlayCampaignRateEvent(
    id,
    auth.user.username,
    b.event_id
  );

  if (result === null) {
    return notFound();
  }

  if (result === "conflict") {
    return badRequest();
  }

  if (result === "rate_limited") {
    return NextResponse.json(
      { limit: RATE_EVENT_LIMIT, remaining: 0 },
      { status: 429 }
    );
  }

  return created(result);
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

  const result = getPlayCampaignRateEvents(id, auth.user.username);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
