import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignFeedEvent,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";

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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.event_id !== "string" ||
    b.event_id.length === 0 ||
    typeof b.text !== "string" ||
    b.text.length === 0
  ) {
    return badRequest();
  }

  const result = createPlayCampaignFeedEvent(id, {
    event_id: b.event_id,
    text: b.text,
  });

  if (result === null) {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return NextResponse.json(result, { status: 201 });
}
