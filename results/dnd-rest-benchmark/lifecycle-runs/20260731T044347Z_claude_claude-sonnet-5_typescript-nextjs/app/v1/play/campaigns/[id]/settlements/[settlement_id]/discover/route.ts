import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  getPlaySettlement,
  getPlayMemberForUser,
  updatePlaySettlement,
} from "../../../../../store.js";
import { serializeSettlementForPlayer } from "../../shared.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string }> },
) {
  const { id: campaignId, settlement_id: settlementId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  if (username === campaign.owner) {
    return Response.json(
      { error: "only joined campaign players may discover settlements" },
      { status: 403 },
    );
  }

  const member = getPlayMemberForUser(campaignId, username);
  if (!member) {
    return Response.json(
      { error: "only joined campaign players may discover settlements" },
      { status: 403 },
    );
  }

  const settlement = getPlaySettlement(campaignId, settlementId);
  if (!settlement) {
    return Response.json(
      { error: `settlement ${settlementId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const characterId = member.character_id;
  if (settlement.discovered_by.includes(characterId)) {
    return Response.json(serializeSettlementForPlayer(settlement, characterId), { status: 200 });
  }

  const updated = updatePlaySettlement(campaignId, {
    ...settlement,
    discovered_by: [...settlement.discovered_by, characterId],
  });

  return Response.json(serializeSettlementForPlayer(updated, characterId), { status: 201 });
}
