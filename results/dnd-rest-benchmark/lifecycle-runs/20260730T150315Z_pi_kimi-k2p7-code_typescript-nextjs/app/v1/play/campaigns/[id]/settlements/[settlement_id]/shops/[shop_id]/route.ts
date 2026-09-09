import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  forbidden,
  notFound,
  ok,
} from "../../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getSettlement,
  getSettlementDiscoveries,
  getShop,
} from "../../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; settlement_id: string; shop_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, settlement_id, shop_id } = await params;

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

  const settlement = getSettlement(id, settlement_id);
  if (!settlement) {
    return notFound();
  }

  const shop = getShop(id, settlement_id, shop_id);
  if (!shop) {
    return notFound();
  }

  if (!isOwner && playerMembership) {
    const discoveredBy = getSettlementDiscoveries(id, settlement_id);
    if (!discoveredBy.includes(playerMembership.character_id)) {
      return notFound();
    }
  }

  return ok(shop);
}
