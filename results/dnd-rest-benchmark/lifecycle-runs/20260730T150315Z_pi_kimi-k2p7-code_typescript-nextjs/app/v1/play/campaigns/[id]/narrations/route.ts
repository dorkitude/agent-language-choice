import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import { createNarration, getPlayCampaign, hasDelegationPower } from "../../../../../lib/storage.js";

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
  const canNarrate = isOwner || hasDelegationPower(id, auth.user.username, "narrate");

  if (!canNarrate) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.text !== "string") {
    return badRequest();
  }

  const actor = isOwner ? "dm" : auth.user.username;
  const result = createNarration(id, actor, b.text);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
