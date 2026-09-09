import { requireBearerAuth } from "../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getSettlement,
  isValidAvailability,
  normalizeSettlementServices,
  updateSettlement,
} from "../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, settlement_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const existing = getSettlement(id, settlement_id);
  if (!existing) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.name) ||
    !isValidAvailability(b.availability)
  ) {
    return badRequest();
  }
  const services = normalizeSettlementServices(b.services);
  if (services === null) {
    return badRequest();
  }

  const result = updateSettlement(id, settlement_id, {
    name: b.name,
    services,
    availability: b.availability,
  });

  if (result === null) {
    return notFound();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return ok(result);
}
