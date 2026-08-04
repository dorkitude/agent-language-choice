import { requireSession } from "../../../../auth/session.js";
import { getUser } from "../../../../auth/store.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayInvitation,
  getPlayMemberForUser,
  hasPendingPlayInvitationForUser,
  hasPlayInvitation,
  listPlayInvitations,
  PlayInvitation,
} from "../../../store.js";

function serializeInvitation(invitation: PlayInvitation) {
  return {
    invitation_id: invitation.invitation_id,
    username: invitation.username,
    character_id: invitation.character_id,
    status: invitation.status,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create invitations",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    invitation_id?: unknown;
    username?: unknown;
    character_id?: unknown;
  };

  const validInvitationId = requireNonEmptyString(body.invitation_id, "invitation_id");
  if (validInvitationId instanceof Response) return validInvitationId;

  const validUsername = requireNonEmptyString(body.username, "username");
  if (validUsername instanceof Response) return validUsername;

  const validCharacterId = requireNonEmptyString(body.character_id, "character_id");
  if (validCharacterId instanceof Response) return validCharacterId;

  const targetUser = getUser(validUsername);
  if (!targetUser || targetUser.role !== "player") {
    return Response.json(
      { error: `${validUsername} is not a registered player` },
      { status: 400 },
    );
  }

  if (hasPlayInvitation(campaignId, validInvitationId)) {
    return Response.json(
      { error: `invitation ${validInvitationId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  if (hasPendingPlayInvitationForUser(campaignId, validUsername)) {
    return Response.json(
      {
        error: `campaign ${campaignId} already has a pending invitation for ${validUsername}`,
      },
      { status: 409 },
    );
  }

  const invitation: PlayInvitation = {
    invitation_id: validInvitationId,
    username: validUsername,
    character_id: validCharacterId,
    status: "pending",
  };
  createPlayInvitation(campaignId, invitation);

  return Response.json(serializeInvitation(invitation), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  const invitations = listPlayInvitations(campaignId);
  const isTarget = invitations.some((invitation) => invitation.username === username);

  if (!isDm && !isMember && !isTarget) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const visibleInvitations = isDm
    ? invitations
    : invitations.filter((invitation) => invitation.username === username);

  return Response.json(
    { invitations: visibleInvitations.map(serializeInvitation) },
    { status: 200 },
  );
}
