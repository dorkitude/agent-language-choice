import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignNpc,
  getPlayCampaign,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

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
    typeof b.npc_id !== "string" ||
    b.npc_id.length === 0 ||
    typeof b.name !== "string" ||
    b.name.length === 0 ||
    typeof b.agenda !== "string" ||
    b.agenda.length === 0 ||
    typeof b.public_status !== "string" ||
    b.public_status.length === 0
  ) {
    return badRequest();
  }

  const result = createPlayCampaignNpc(id, {
    npc_id: b.npc_id,
    name: b.name,
    agenda: b.agenda,
    public_status: b.public_status,
  });

  if (!result) {
    return conflict();
  }

  return created({
    npc_id: result.npc_id,
    name: result.name,
    agenda: result.agenda,
    public_status: result.public_status,
  });
}
