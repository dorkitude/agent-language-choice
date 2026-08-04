import { getCampaign } from "../../../../lib/campaigns";
import { LOOT_TIERS } from "../../../../lib/dm";
import { badRequest, json, notFound, readObject } from "../../../../lib/http";
import { asCount, isValidId } from "../../../../lib/validation";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readObject(request);
  if (!body) return badRequest("body must be a JSON object");

  const campaignId = body.campaign_id;
  if (!isValidId(campaignId)) return badRequest("campaign_id must be a valid identifier");
  if (!getCampaign(campaignId)) return notFound("campaign not found");

  const tier = asCount(body.tier, 1);
  if (tier === undefined || !(tier in LOOT_TIERS)) {
    return badRequest("tier must be an integer between 1 and 4");
  }

  /** The seed is accepted for API shape; the parcel table is already fixed. */
  if (body.seed !== undefined && body.seed !== null && asCount(body.seed, 0) === undefined) {
    return badRequest("seed must be a non-negative integer");
  }

  const parcel = LOOT_TIERS[tier]!;
  return json({
    campaign_id: campaignId,
    coins_gp: parcel.coins_gp,
    items: parcel.items.map((item) => ({ ...item })),
  });
}
