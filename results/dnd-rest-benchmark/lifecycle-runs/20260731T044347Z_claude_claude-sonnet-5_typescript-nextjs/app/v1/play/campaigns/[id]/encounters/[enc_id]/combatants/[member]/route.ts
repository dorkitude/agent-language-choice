import { requireSession } from "../../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../../http.js";
import { getPlayEncounter, updatePlayEncounter } from "../../../../../../store.js";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string; member: string }> },
) {
  const { id: campaignId, enc_id: encounterId, member: memberUsername } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may unbind a combatant",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const combatants = encounter.combatants ?? [];
  if (!combatants.some((combatant) => combatant.member === memberUsername)) {
    return Response.json(
      { error: `member ${memberUsername} not found in encounter ${encounterId}` },
      { status: 404 },
    );
  }

  updatePlayEncounter({
    ...encounter,
    combatants: combatants.filter((combatant) => combatant.member !== memberUsername),
  });

  return Response.json({ removed: memberUsername }, { status: 200 });
}
