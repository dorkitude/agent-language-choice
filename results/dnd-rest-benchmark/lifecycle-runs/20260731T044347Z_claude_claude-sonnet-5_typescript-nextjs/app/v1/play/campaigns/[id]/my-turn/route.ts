import { requireSession } from "../../../../auth/session.js";
import { requirePlayCampaign, listRecentPlayEventSummaries } from "../../../http.js";
import { getPlayMemberForUser } from "../../../store.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  if (session.user.role !== "player") {
    return Response.json({ error: "only a player may view their turn context" }, { status: 403 });
  }

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const member = getPlayMemberForUser(campaignId, username);
  if (!member) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const currentActor = campaign.current_actor ?? null;
  const recentEvents = listRecentPlayEventSummaries(campaignId);

  return Response.json(
    {
      campaign_id: campaign.id,
      is_my_turn: currentActor === username,
      current_actor: currentActor,
      character: { id: member.character_id, name: member.name },
      recent_events: recentEvents,
    },
    { status: 200 },
  );
}
