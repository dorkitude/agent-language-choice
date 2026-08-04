import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  awardEncounterRewards,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";
import { isNonNegativeInteger } from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, enc_id } = await params;

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
  if (!isNonNegativeInteger(b.xp)) {
    return badRequest();
  }

  if (!Array.isArray(b.loot)) {
    return badRequest();
  }

  const loot: { slug: string; quantity: number }[] = [];
  for (const entry of b.loot) {
    if (typeof entry !== "object" || entry === null) {
      return badRequest();
    }
    const e = entry as Record<string, unknown>;
    if (typeof e.slug !== "string" || e.slug.length === 0) {
      return badRequest();
    }
    if (!Number.isInteger(e.quantity) || (e.quantity as number) <= 0) {
      return badRequest();
    }
    loot.push({ slug: e.slug, quantity: e.quantity as number });
  }

  const result = awardEncounterRewards(id, enc_id, b.xp as number, loot);
  if (result === null) {
    return notFound();
  }
  if (result === "already_awarded") {
    return conflict();
  }

  return ok(result);
}
