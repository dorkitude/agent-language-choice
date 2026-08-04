import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import { createPlayNpc, hasPlayNpc } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(campaign, session.user.username, "only the campaign dm may create npcs");
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    npc_id?: unknown;
    name?: unknown;
    agenda?: unknown;
    public_status?: unknown;
  };

  const validNpcId = requireNonEmptyString(body.npc_id, "npc_id");
  if (validNpcId instanceof Response) return validNpcId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const validAgenda = requireNonEmptyString(body.agenda, "agenda");
  if (validAgenda instanceof Response) return validAgenda;

  const validPublicStatus = requireNonEmptyString(body.public_status, "public_status");
  if (validPublicStatus instanceof Response) return validPublicStatus;

  if (hasPlayNpc(campaignId, validNpcId)) {
    return Response.json(
      { error: `npc ${validNpcId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const npc = createPlayNpc({
    campaign_id: campaignId,
    npc_id: validNpcId,
    name: validName,
    agenda: validAgenda,
    public_status: validPublicStatus,
  });

  return Response.json(
    { npc_id: npc.npc_id, name: npc.name, agenda: npc.agenda, public_status: npc.public_status },
    { status: 201 },
  );
}
