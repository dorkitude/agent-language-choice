import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlaySettlement,
  getPlayMemberForUser,
  hasPlaySettlement,
  listPlaySettlements,
  PlaySettlement,
} from "../../../store.js";
import {
  serializeSettlementForDm,
  serializeSettlementForPlayer,
  validateAvailability,
  validateServices,
} from "./shared.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create settlements",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    settlement_id?: unknown;
    name?: unknown;
    services?: unknown;
    availability?: unknown;
  };

  const validSettlementId = requireNonEmptyString(body.settlement_id, "settlement_id");
  if (validSettlementId instanceof Response) return validSettlementId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  const validServices = validateServices(body.services);
  if (validServices instanceof Response) return validServices;

  const validAvailability = validateAvailability(body.availability);
  if (validAvailability instanceof Response) return validAvailability;

  if (hasPlaySettlement(campaignId, validSettlementId)) {
    return Response.json(
      { error: `settlement ${validSettlementId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const settlement: PlaySettlement = {
    settlement_id: validSettlementId,
    name: validName,
    services: validServices,
    availability: validAvailability,
    discovered_by: [],
  };

  createPlaySettlement(campaignId, settlement);

  return Response.json(serializeSettlementForDm(settlement), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  const isMember = isDm || member !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const allSettlements = listPlaySettlements(campaignId);
  if (isDm) {
    return Response.json(
      { settlements: allSettlements.map(serializeSettlementForDm) },
      { status: 200 },
    );
  }

  const characterId = member!.character_id;
  const visibleSettlements = allSettlements
    .filter((settlement) => settlement.discovered_by.includes(characterId))
    .map((settlement) => serializeSettlementForPlayer(settlement, characterId));

  return Response.json({ settlements: visibleSettlements }, { status: 200 });
}
