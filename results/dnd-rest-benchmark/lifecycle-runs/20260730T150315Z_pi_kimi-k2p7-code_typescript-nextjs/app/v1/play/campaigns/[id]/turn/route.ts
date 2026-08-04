import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignState,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

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
  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const state = getPlayCampaignState(id);
  if (!state) {
    return notFound();
  }

  const phase = state.current_actor === campaign.owner ? "dm" : "player";
  const queue: string[] = [];
  for (const m of members) {
    queue.push(m.username, "dm");
  }

  return NextResponse.json({
    campaign_id: state.campaign_id,
    current_actor: state.current_actor,
    phase,
    turn_number: state.turn_number,
    queue,
    overdue: false,
    logical_deadline: state.turn_number + 1,
  });
}
