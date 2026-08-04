import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../../lib/http.js";
import { isNonEmptyString } from "../../../../../../lib/validate.js";
import {
  createNudge,
  getPlayCampaign,
  getPlayCampaignState,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const state = getPlayCampaignState(id);
  if (!state) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isNonEmptyString(b.message)) {
    return badRequest();
  }

  const result = createNudge(id, auth.user.username, b.message);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(
    {
      actor: auth.user.username,
      target: state.current_actor,
      message: b.message,
      nudge_count: result.nudge_count,
    },
    { status: 201 }
  );
}
