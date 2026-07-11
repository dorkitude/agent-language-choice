const TIER_1_LOOT = {
  coins_gp: 75,
  items: [{ slug: "healing-potion", quantity: 2 }],
};

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const campaignId = body.campaign_id;
    if (typeof campaignId !== "string" || campaignId.length === 0) {
      throw new Error("campaign_id must be a non-empty string");
    }

    const tier = body.tier;
    if (typeof tier !== "number" || !Number.isInteger(tier)) {
      throw new Error("tier must be an integer");
    }
    if (tier !== 1) {
      throw new Error("tier not supported");
    }

    return Response.json({
      campaign_id: campaignId,
      ...TIER_1_LOOT,
    });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    return Response.json({ error: message }, { status: 400 });
  }
}
