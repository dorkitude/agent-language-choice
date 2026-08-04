import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignState,
  getNarrations,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
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

  const members = getPlayCampaignMembers(id);
  const party = members.map((m) => ({
    username: m.username,
    character_id: m.character_id,
    name: m.name,
    class: m.class,
  }));

  const recentEvents = getNarrations(id).map((event) => ({
    sequence: event.sequence,
    kind: event.kind,
    actor: event.actor,
    text: event.text,
    type: event.type,
  }));

  return NextResponse.json({
    needs_attention: state.current_actor === campaign.owner,
    current_actor: state.current_actor,
    party,
    recent_events: recentEvents,
  });
}
