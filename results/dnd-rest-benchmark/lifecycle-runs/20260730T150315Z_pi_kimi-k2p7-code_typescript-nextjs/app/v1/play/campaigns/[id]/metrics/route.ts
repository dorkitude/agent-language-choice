import { requireBearerAuth } from "../../../../../lib/auth.js";
import { forbidden, notFound, ok } from "../../../../../lib/http.js";
import { getPlayCampaign, getPlayCampaignServiceMetrics } from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const metrics = getPlayCampaignServiceMetrics(id);
  if (!metrics) {
    return notFound();
  }

  return ok(metrics);
}
