import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayMember,
  getPlayInvitation,
  PlayMember,
  STARTING_GOLD,
  updatePlayInvitation,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; invitation_id: string }> },
) {
  const { id: campaignId, invitation_id: invitationId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const invitation = getPlayInvitation(campaignId, invitationId);
  if (!invitation) {
    return Response.json(
      { error: `invitation ${invitationId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const username = session.user.username;
  if (username !== invitation.username) {
    return Response.json(
      { error: `only ${invitation.username} may accept invitation ${invitationId}` },
      { status: 403 },
    );
  }

  if (invitation.status === "accepted") {
    return Response.json(
      { error: `invitation ${invitationId} has already been accepted` },
      { status: 409 },
    );
  }

  const member: PlayMember = {
    campaign_id: campaignId,
    username,
    character_id: invitation.character_id,
    name: username,
    class: "adventurer",
    owner: username,
    gold: STARTING_GOLD,
  };
  createPlayMember(member);

  const accepted = { ...invitation, status: "accepted" as const };
  updatePlayInvitation(campaignId, accepted);

  return Response.json(
    {
      invitation_id: accepted.invitation_id,
      username: accepted.username,
      character_id: accepted.character_id,
      status: accepted.status,
    },
    { status: 200 },
  );
}
