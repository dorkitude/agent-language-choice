import { requireSession } from "../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayEncounter, updatePlayEncounter } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may close this encounter",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  updatePlayEncounter({ ...encounter, status: "closed" });

  return Response.json(
    { id: encounter.id, status: "closed", xp_awarded: encounter.rewards?.xp ?? 0 },
    { status: 200 },
  );
}
