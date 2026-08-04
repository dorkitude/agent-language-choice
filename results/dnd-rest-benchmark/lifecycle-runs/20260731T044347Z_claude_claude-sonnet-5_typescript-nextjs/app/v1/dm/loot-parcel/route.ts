interface LootItem {
  slug: string;
  quantity: number;
}

import { parseJsonBody } from "../../http.js";

const TIER_1_ITEMS: LootItem[] = [{ slug: "healing-potion", quantity: 2 }];
const TIER_1_COINS_GP = 75;

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { campaign_id, tier, seed } = (body ?? {}) as {
    campaign_id?: string;
    tier?: number;
    seed?: number;
  };

  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return Response.json({ error: "campaign_id is required" }, { status: 400 });
  }
  if (typeof tier !== "number" || !Number.isInteger(tier) || tier < 1) {
    return Response.json({ error: "tier must be a positive integer" }, { status: 400 });
  }
  if (seed !== undefined && typeof seed !== "number") {
    return Response.json({ error: "seed must be a number" }, { status: 400 });
  }

  const coinsGp = TIER_1_COINS_GP * tier;
  const items = TIER_1_ITEMS.map((item) => ({ slug: item.slug, quantity: item.quantity * tier }));

  return Response.json({
    campaign_id,
    coins_gp: coinsGp,
    items,
  });
}
