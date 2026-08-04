import { requireSession } from "../../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../../http.js";
import { getPlayEncounter, updatePlayEncounter } from "../../../../../../store.js";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string; monster_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId, monster_id: monsterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may remove a monster",
  );
  if (ownerCheck) return ownerCheck;

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const monsters = encounter.monsters ?? [];
  if (!monsters.some((monster) => monster.monster_id === monsterId)) {
    return Response.json({ error: `monster ${monsterId} not found` }, { status: 404 });
  }

  updatePlayEncounter({
    ...encounter,
    monsters: monsters.filter((monster) => monster.monster_id !== monsterId),
  });

  return Response.json({ removed: monsterId }, { status: 200 });
}
