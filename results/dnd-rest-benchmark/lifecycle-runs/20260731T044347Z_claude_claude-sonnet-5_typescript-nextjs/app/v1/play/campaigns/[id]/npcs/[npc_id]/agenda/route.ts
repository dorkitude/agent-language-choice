import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import { getPlayNpc, updatePlayNpc } from "../../../../../store.js";

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> },
) {
  const { id: campaignId, npc_id: npcId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may update npc agendas",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { agenda?: unknown; public_status?: unknown };

  const validAgenda = requireNonEmptyString(body.agenda, "agenda");
  if (validAgenda instanceof Response) return validAgenda;

  const validPublicStatus = requireNonEmptyString(body.public_status, "public_status");
  if (validPublicStatus instanceof Response) return validPublicStatus;

  const npc = getPlayNpc(campaignId, npcId);
  if (!npc) {
    return Response.json({ error: `npc ${npcId} not found` }, { status: 404 });
  }

  const updated = updatePlayNpc({
    ...npc,
    agenda: validAgenda,
    public_status: validPublicStatus,
  });

  return Response.json(
    {
      npc_id: updated.npc_id,
      name: updated.name,
      agenda: updated.agenda,
      public_status: updated.public_status,
    },
    { status: 200 },
  );
}
