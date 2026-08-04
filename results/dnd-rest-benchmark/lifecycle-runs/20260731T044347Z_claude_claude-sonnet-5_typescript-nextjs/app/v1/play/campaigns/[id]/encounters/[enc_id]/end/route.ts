import { requireSession } from "../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayEncounter, updatePlayCampaign, updatePlayEncounter } from "../../../../../store.js";

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
    "only the owning dm may end this encounter",
  );
  if (ownerCheck) return ownerCheck;

  if (campaign.phase !== "combat") {
    return Response.json(
      { error: `play campaign ${campaignId} is not in combat` },
      { status: 409 },
    );
  }

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  if (encounter.status === "active") {
    updatePlayEncounter({ ...encounter, status: "closed" });
  }

  const restoredActor = campaign.pre_combat_actor ?? campaign.current_actor;
  const restored = {
    ...campaign,
    phase: "exploration" as const,
    current_actor: restoredActor,
    pre_combat_actor: undefined,
  };
  updatePlayCampaign(restored);

  return Response.json(
    {
      campaign_id: restored.id,
      status: restored.status,
      phase: restored.phase,
      current_actor: restored.current_actor ?? null,
    },
    { status: 200 },
  );
}
