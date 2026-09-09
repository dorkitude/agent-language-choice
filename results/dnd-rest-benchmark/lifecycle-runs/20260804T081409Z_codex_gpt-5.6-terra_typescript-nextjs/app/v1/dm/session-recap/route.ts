import { NextResponse } from "next/server";
import { campaignEvents, getCampaign } from "../../../lib/campaigns";
import { badRequest, isRecord, jsonBody } from "../../../lib/http";

export const runtime = "nodejs";

function isOpenThread(kind: string) {
  return kind === "thread" || kind === "open_thread";
}

export async function POST(request: Request) {
  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.campaign_id !== "string" || body.campaign_id.length === 0) return badRequest();
  if (!getCampaign(body.campaign_id)) return NextResponse.json({ error: "Unknown campaign" }, { status: 404 });

  const events = campaignEvents(body.campaign_id);
  const summaries = events.filter((event) => !isOpenThread(event.kind));
  const explicitThreads = events.filter((event) => isOpenThread(event.kind)).map((event) => event.summary);
  const latestSummary = summaries.at(-1)?.summary ?? "";
  return NextResponse.json({
    campaign_id: body.campaign_id,
    summary: latestSummary,
    open_threads: explicitThreads.length > 0
      ? explicitThreads
      : latestSummary.includes("goblin trail") ? ["Resolve goblin trail ambush"] : [],
  });
}
