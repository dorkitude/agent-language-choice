import { requireSession } from "../../../../auth/session.js";
import { getFirstPlayMember, listPlayMembers, updatePlayCampaign } from "../../../store.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may start this campaign",
  );
  if (ownerCheck) return ownerCheck;

  if (campaign.status !== "lobby") {
    return Response.json({ error: `play campaign ${campaignId} cannot be started` }, { status: 409 });
  }

  if (listPlayMembers(campaignId).length < 2) {
    return Response.json({ error: `play campaign ${campaignId} needs at least two party members` }, { status: 409 });
  }

  // Defensive fallback: the length check above already guarantees a member
  // row exists, but we still narrow the type here rather than assert it.
  const firstMember = getFirstPlayMember(campaignId);
  if (!firstMember) {
    return Response.json({ error: `play campaign ${campaignId} needs at least two party members` }, { status: 409 });
  }

  const started = {
    ...campaign,
    status: "active" as const,
    current_actor: firstMember.username,
    turn_number: 1,
    phase: "exploration" as const,
  };
  updatePlayCampaign(started);

  return Response.json(
    {
      id: started.id,
      status: started.status,
      current_actor: started.current_actor,
      turn_number: started.turn_number,
    },
    { status: 200 },
  );
}
