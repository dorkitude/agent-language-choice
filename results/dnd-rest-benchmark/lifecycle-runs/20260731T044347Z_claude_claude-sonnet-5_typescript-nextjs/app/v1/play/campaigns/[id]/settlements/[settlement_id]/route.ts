import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import { getPlaySettlement, PlaySettlement, updatePlaySettlement } from "../../../../store.js";
import {
  serializeSettlementForDm,
  validateAvailability,
  validateServices,
} from "../shared.js";

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> },
) {
  const { id: campaignId, settlement_id: settlementId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may replace settlements",
  );
  if (ownerCheck) return ownerCheck;

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    return Response.json(
      { error: `settlement ${settlementId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    name?: unknown;
    services?: unknown;
    availability?: unknown;
  };

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const validServices = validateServices(body.services);
  if (validServices instanceof Response) return validServices;

  const validAvailability = validateAvailability(body.availability);
  if (validAvailability instanceof Response) return validAvailability;

  const updated: PlaySettlement = {
    ...settlement,
    name: validName,
    services: validServices,
    availability: validAvailability,
  };

  updatePlaySettlement(campaignId, updated);

  return Response.json(serializeSettlementForDm(updated), { status: 200 });
}
