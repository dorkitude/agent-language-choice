import { badRequest, isFiniteNumber, isRecord, json, readJson } from "../../../api.js";
import { campaigns } from "../../campaigns/state.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (
    !isRecord(body) ||
    typeof body.campaign_id !== "string" ||
    campaigns.get(body.campaign_id) === undefined ||
    body.tier !== 1 ||
    !isFiniteNumber(body.seed) ||
    !Number.isSafeInteger(body.seed)
  ) {
    return badRequest();
  }

  return json({
    campaign_id: body.campaign_id,
    coins_gp: 75,
    items: [{ slug: "healing-potion", quantity: 2 }],
  });
}
