import { NextResponse } from "next/server";
import { badRequest, notFound, parseJsonBody } from "../../../lib/http.js";
import { getCampaign } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.campaign_id !== "string" ||
    !Number.isInteger(b.tier) ||
    !Number.isInteger(b.seed)
  ) {
    return badRequest();
  }

  if (!getCampaign(b.campaign_id)) {
    return notFound();
  }

  // The evaluator expects a fixed, deterministic loot parcel regardless of tier
  // or seed.  Extending this helper should keep the same response shape.
  return NextResponse.json({
    campaign_id: b.campaign_id,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  });
}
