import { requireSession } from "../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign, listRecentPlayEventSummaries } from "../../../../http.js";
import { listPlayMembers } from "../../../../store.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(campaign, session.user.username, "only the owning dm may view gm status");
  if (ownerCheck) return ownerCheck;

  const currentActor = campaign.current_actor ?? null;
  const party = listPlayMembers(campaignId).map((member) => ({
    username: member.username,
    character: { id: member.character_id, name: member.name, class: member.class },
  }));
  const recentEvents = listRecentPlayEventSummaries(campaignId);

  return Response.json(
    {
      campaign_id: campaign.id,
      needs_attention: currentActor === campaign.owner,
      current_actor: currentActor,
      party,
      recent_events: recentEvents,
    },
    { status: 200 },
  );
}
