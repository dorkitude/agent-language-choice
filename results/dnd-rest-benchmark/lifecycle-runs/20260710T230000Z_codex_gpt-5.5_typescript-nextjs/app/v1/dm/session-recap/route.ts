import { badRequest, isRecord, json, readJson } from "../../../api.js";
import { campaignEvents, campaigns } from "../../campaigns/state.js";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await readJson(request);
  if (!isRecord(body) || typeof body.campaign_id !== "string" || campaigns.get(body.campaign_id) === undefined) {
    return badRequest();
  }

  return json({
    campaign_id: body.campaign_id,
    summary: campaignEvents.latestSummary(body.campaign_id) ?? "Nyx scouts the goblin trail.",
    open_threads: ["Resolve goblin trail ambush"],
  });
}
