import { requireSession } from "../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import {
  createPlayDelegationAuditEntry,
  getPlayDelegation,
  PlayDelegation,
  updatePlayDelegation,
} from "../../../../store.js";

function serializeDelegation(delegation: PlayDelegation) {
  return {
    username: delegation.username,
    powers: delegation.powers,
    active: delegation.active,
  };
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string; username: string }> },
) {
  const { id: campaignId, username } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign owner may revoke delegation",
  );
  if (ownerCheck) return ownerCheck;

  const existing = getPlayDelegation(campaignId, username);
  if (!existing || !existing.active) {
    return Response.json(
      { error: `${username} has no active delegation in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const delegation: PlayDelegation = { ...existing, active: false };
  updatePlayDelegation(campaignId, delegation);

  createPlayDelegationAuditEntry(campaignId, {
    username,
    action: "revoked",
    powers: delegation.powers,
  });

  return Response.json(serializeDelegation(delegation), { status: 200 });
}
