import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayDelegation,
  createPlayDelegationAuditEntry,
  getPlayDelegation,
  getPlayMemberForUser,
  PlayDelegation,
  PlayDelegationPower,
  updatePlayDelegation,
  VALID_DELEGATION_POWERS,
} from "../../../store.js";

function serializeDelegation(delegation: PlayDelegation) {
  return {
    username: delegation.username,
    powers: delegation.powers,
    active: delegation.active,
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
    "only the campaign owner may grant delegation",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { username?: unknown; powers?: unknown };

  const validUsername = requireNonEmptyString(body.username, "username");
  if (validUsername instanceof Response) return validUsername;

  if (!Array.isArray(body.powers) || body.powers.length === 0) {
    return Response.json({ error: "powers must be a nonempty array" }, { status: 400 });
  }

  const powers = body.powers as unknown[];
  if (!powers.every((power) => typeof power === "string")) {
    return Response.json({ error: "powers must be an array of strings" }, { status: 400 });
  }

  const uniquePowers = new Set(powers as string[]);
  if (uniquePowers.size !== powers.length) {
    return Response.json({ error: "powers must not contain duplicates" }, { status: 400 });
  }

  if (!powers.every((power) => VALID_DELEGATION_POWERS.includes(power as PlayDelegationPower))) {
    return Response.json({ error: "powers contains an invalid value" }, { status: 400 });
  }

  if (getPlayMemberForUser(campaignId, validUsername) === undefined) {
    return Response.json(
      { error: `${validUsername} is not a member of campaign ${campaignId}` },
      { status: 400 },
    );
  }

  const existing = getPlayDelegation(campaignId, validUsername);
  if (existing && existing.active) {
    return Response.json(
      { error: `${validUsername} already has an active delegation in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const delegation: PlayDelegation = {
    username: validUsername,
    powers: powers as PlayDelegationPower[],
    active: true,
  };

  if (existing) {
    updatePlayDelegation(campaignId, delegation);
  } else {
    createPlayDelegation(campaignId, delegation);
  }

  createPlayDelegationAuditEntry(campaignId, {
    username: validUsername,
    action: "granted",
    powers: delegation.powers,
  });

  return Response.json(serializeDelegation(delegation), { status: 201 });
}
