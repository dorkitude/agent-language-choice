import { requireSession } from "../../../../auth/session.js";
import { hasPlayMemberForUser, listPlayMembers } from "../../../store.js";
import { requirePlayCampaign } from "../../../http.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const currentActor = campaign.current_actor ?? null;
  const phase = currentActor === campaign.owner ? "dm" : "player";

  // The turn queue mirrors the actual play loop: each player's action is
  // always followed by the dm's resolution before the next player goes.
  const members = listPlayMembers(campaignId);
  const queue: string[] = [];
  for (const member of members) {
    queue.push(member.username);
    queue.push(campaign.owner);
  }

  const turnNumber = campaign.turn_number ?? 0;

  return Response.json(
    {
      campaign_id: campaign.id,
      current_actor: currentActor,
      phase,
      turn_number: turnNumber,
      queue,
      overdue: false,
      logical_deadline: turnNumber + 1,
    },
    { status: 200 },
  );
}
