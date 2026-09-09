import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  updatePlayCampaignRelationship,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  {
    params,
  }: {
    params: Promise<{ id: string; source_id: string; target_id: string; kind: string }>;
  }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, source_id, target_id, kind } = await params;

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
  if (typeof b.score !== "number" || !Number.isInteger(b.score)) {
    return badRequest();
  }
  const score = b.score;
  if (score < -100 || score > 100) {
    return badRequest();
  }

  const result = updatePlayCampaignRelationship(
    id,
    source_id,
    target_id,
    kind,
    score
  );
  if (!result) {
    return notFound();
  }

  return ok(result);
}
