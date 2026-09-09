import { requireBearerAuth } from "../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../lib/http.js";
import { getPlayCampaign, getPlayCampaignMember } from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

const DM_ONBOARDING = {
  role: "dm",
  next_steps: ["configure-safety", "invite-players", "start-campaign"],
  can_mutate: true,
};

const PLAYER_ONBOARDING = {
  role: "player",
  next_steps: ["review-party", "take-turn", "submit-action"],
  can_mutate: true,
};

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = auth.user.username === campaign.owner;
  const isMember = getPlayCampaignMember(id, auth.user.username) !== null;

  if (isOwner) {
    return ok(DM_ONBOARDING);
  }

  if (isMember) {
    return ok(PLAYER_ONBOARDING);
  }

  return forbidden();
}
