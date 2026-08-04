import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, conflict, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  createResolution,
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignState,
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

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  const isOwner = campaign.owner === auth.user.username;

  if (!isMember && !isOwner) {
    return forbidden();
  }

  const state = getPlayCampaignState(id);
  if (!state) {
    return notFound();
  }

  if (state.current_actor !== campaign.owner || !isOwner) {
    return conflict();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.text !== "string") {
    return badRequest();
  }

  const result = createResolution(id, campaign.owner, b.text);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
