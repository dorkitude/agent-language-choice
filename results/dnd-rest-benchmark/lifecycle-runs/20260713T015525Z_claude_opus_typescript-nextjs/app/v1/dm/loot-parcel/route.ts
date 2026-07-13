import { NextResponse } from "next/server";

// Deterministic loot parcels keyed by tier for this benchmark.
const LOOT_PARCELS: Record<
  number,
  { coins_gp: number; items: { slug: string; quantity: number }[] }
> = {
  1: { coins_gp: 75, items: [{ slug: "healing-potion", quantity: 2 }] },
};

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const obj =
    typeof body === "object" && body !== null
      ? (body as Record<string, unknown>)
      : {};
  const campaignId = obj.campaign_id;
  const tier = obj.tier;

  if (typeof campaignId !== "string" || campaignId.length === 0) {
    return NextResponse.json({ error: "invalid campaign_id" }, { status: 400 });
  }
  if (typeof tier !== "number" || !Number.isInteger(tier)) {
    return NextResponse.json({ error: "invalid tier" }, { status: 400 });
  }

  const parcel = LOOT_PARCELS[tier];
  if (!parcel) {
    return NextResponse.json({ error: "unsupported tier" }, { status: 400 });
  }

  return NextResponse.json({
    campaign_id: campaignId,
    coins_gp: parcel.coins_gp,
    items: parcel.items.map((item) => ({ ...item })),
  });
}
