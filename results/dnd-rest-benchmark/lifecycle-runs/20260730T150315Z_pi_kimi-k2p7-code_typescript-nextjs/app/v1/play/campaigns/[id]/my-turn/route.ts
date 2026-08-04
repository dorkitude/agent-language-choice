import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignState,
  getNarrations,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "player");
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const member = members.find((m) => m.username === auth.user.username);
  if (!member) {
    return forbidden();
  }

  const state = getPlayCampaignState(id);
  if (!state) {
    return notFound();
  }

  const isMyTurn = state.current_actor === auth.user.username;
  const recentEvents = getNarrations(id).map((event) => ({
    sequence: event.sequence,
    kind: event.kind,
    actor: event.actor,
    text: event.text,
    type: event.type,
  }));

  return NextResponse.json({
    is_my_turn: isMyTurn,
    current_actor: state.current_actor,
    character: { id: member.character_id, name: member.name },
    recent_events: recentEvents,
  });
}
