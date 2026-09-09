import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignProjectionEvent,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import type { PlayCampaignProjectionEventInput } from "../../../../../lib/storage.js";
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
  if (isOwner) {
    return forbidden();
  }

  if (!getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.event_id)) {
    return badRequest();
  }

  if (b.kind !== "set-story" && b.kind !== "increment-danger") {
    return badRequest();
  }

  if (b.kind === "set-story") {
    if (!isNonEmptyString(b.value)) {
      return badRequest();
    }
  } else {
    if (b.value !== undefined) {
      return badRequest();
    }
  }

  const input: PlayCampaignProjectionEventInput = {
    event_id: b.event_id,
    kind: b.kind,
    value: b.kind === "set-story" ? b.value : undefined,
  };

  const result = createPlayCampaignProjectionEvent(id, input);

  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return created(result);
}
