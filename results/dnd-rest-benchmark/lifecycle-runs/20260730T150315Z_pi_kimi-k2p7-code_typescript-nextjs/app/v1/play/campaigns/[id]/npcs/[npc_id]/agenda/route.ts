import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  updatePlayCampaignNpcAgenda,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, npc_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.agenda !== "string" ||
    b.agenda.length === 0 ||
    typeof b.public_status !== "string" ||
    b.public_status.length === 0
  ) {
    return badRequest();
  }

  const result = updatePlayCampaignNpcAgenda(id, npc_id, {
    agenda: b.agenda,
    public_status: b.public_status,
  });

  if (!result) {
    return notFound();
  }

  return ok({
    npc_id: result.npc_id,
    name: result.name,
    agenda: result.agenda,
    public_status: result.public_status,
  });
}
