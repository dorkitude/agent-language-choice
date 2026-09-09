import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createSettlement,
  getPlayCampaign,
  getPlayCampaignMembers,
  getSettlementDiscoveries,
  getSettlements,
  isValidAvailability,
  normalizeSettlementServices,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";
import type { Settlement } from "../../../../../lib/types.js";

export const dynamic = "force-dynamic";

function toPlayerSettlement(
  settlement: Settlement,
  characterId: string
): Settlement {
  return {
    ...settlement,
    discovered_by: settlement.discovered_by.includes(characterId)
      ? [characterId]
      : [],
  };
}

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
    !isNonEmptyString(b.settlement_id) ||
    !isNonEmptyString(b.name) ||
    !isValidAvailability(b.availability)
  ) {
    return badRequest();
  }
  const services = normalizeSettlementServices(b.services);
  if (services === null) {
    return badRequest();
  }

  const result = createSettlement(id, {
    settlement_id: b.settlement_id,
    name: b.name,
    services,
    availability: b.availability,
  });

  if (result === null) {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return created(result);
}

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

  const members = getPlayCampaignMembers(id);
  const isOwner = campaign.owner === auth.user.username;
  const playerMembership = members.find((m) => m.username === auth.user.username);

  if (!isOwner && !playerMembership) {
    return forbidden();
  }

  const allSettlements = getSettlements(id);

  if (isOwner) {
    const dmSettlements = allSettlements.map((s) => ({
      ...s,
      discovered_by: getSettlementDiscoveries(id, s.settlement_id),
    }));
    return ok({ settlements: dmSettlements });
  }

  if (!playerMembership) {
    return forbidden();
  }

  const characterId = playerMembership.character_id;
  const discoveredByCharacter = allSettlements
    .map((s) => ({
      ...s,
      discovered_by: getSettlementDiscoveries(id, s.settlement_id),
    }))
    .filter((s) => s.discovered_by.includes(characterId))
    .map((s) => toPlayerSettlement(s, characterId));

  return ok({ settlements: discoveredByCharacter });
}
