import { requireSession } from "../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../http.js";
import { getPlayMemberForUser, getPlayNpc } from "../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> },
) {
  const { id: campaignId, npc_id: npcId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const npc = getPlayNpc(campaignId, npcId);
  if (!npc) {
    return Response.json({ error: `npc ${npcId} not found` }, { status: 404 });
  }

  if (isDm) {
    return Response.json(
      { npc_id: npc.npc_id, name: npc.name, agenda: npc.agenda, public_status: npc.public_status },
      { status: 200 },
    );
  }

  return Response.json(
    { npc_id: npc.npc_id, name: npc.name, public_status: npc.public_status },
    { status: 200 },
  );
}
