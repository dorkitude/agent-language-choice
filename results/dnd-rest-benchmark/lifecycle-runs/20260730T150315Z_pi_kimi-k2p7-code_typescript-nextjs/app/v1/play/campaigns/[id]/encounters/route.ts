import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, created, forbidden, notFound, conflict, parseJsonBody } from "../../../../../lib/http.js";
import { createPlayCampaignEncounter, getPlayCampaign } from "../../../../../lib/storage.js";

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
  if (typeof b.id !== "string" || typeof b.name !== "string") {
    return badRequest();
  }

  const result = createPlayCampaignEncounter(id, { id: b.id, name: b.name });
  if (!result) {
    return conflict();
  }

  return created(result);
}
