import { requireSession } from "../../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import { getPlayMemberForUser, getPlayShop, getPlaySettlement } from "../../../../../../store.js";
import { serializeShop } from "../shared.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string; shop_id: string }> },
) {
  const { id: campaignId, settlement_id: settlementId, shop_id: shopId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  if (!isDm && !member) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
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

  if (!isDm && !settlement.discovered_by.includes(member!.character_id)) {
    return Response.json(
      { error: `settlement ${settlementId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const shop = getPlayShop(campaignId, settlementId, shopId);
  if (!shop) {
    return Response.json(
      { error: `shop ${shopId} not found in settlement ${settlementId}` },
      { status: 404 },
    );
  }

  return Response.json(serializeShop(shop), { status: 200 });
}
