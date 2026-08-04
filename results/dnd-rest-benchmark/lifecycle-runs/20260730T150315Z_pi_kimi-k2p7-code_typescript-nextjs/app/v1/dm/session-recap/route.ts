import { NextResponse } from "next/server";
import { openThreadFromSummary } from "../../../lib/engine.js";
import { badRequest, notFound, parseJsonBody } from "../../../lib/http.js";
import { getCampaign, getLatestCampaignEvent } from "../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (typeof b.campaign_id !== "string") {
    return badRequest();
  }

  if (!getCampaign(b.campaign_id)) {
    return notFound();
  }

  const latest = getLatestCampaignEvent(b.campaign_id);
  const summary = latest?.summary ?? "No recent events";
  const open_threads = latest ? [openThreadFromSummary(latest.summary)] : [];

  return NextResponse.json({
    campaign_id: b.campaign_id,
    summary,
    open_threads,
  });
}
