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
  configurePlayCampaignQuestRewards,
  getPlayCampaign,
  isValidInventoryItemId,
} from "../../../../../../../lib/storage.js";
import {
  isNonNegativeInteger,
  isPositiveInteger,
} from "../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, quest_id } = await params;
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
  if (
    typeof b.items !== "object" ||
    b.items === null ||
    Array.isArray(b.items)
  ) {
    return badRequest();
  }

  const items: Record<string, number> = {};
  for (const [key, value] of Object.entries(b.items)) {
    if (!isPositiveInteger(value)) {
      return badRequest();
    }
    if (!isValidInventoryItemId(key)) {
      return badRequest();
    }
    items[key] = value as number;
  }

  const result = configurePlayCampaignQuestRewards(id, quest_id, {
    xp: b.xp as number,
    items,
  });

  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return ok(result);
}
