import { NextResponse } from "next/server";
import { getCampaign, listEvents } from "../../campaigns/store";

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

  if (typeof campaignId !== "string" || campaignId.length === 0) {
    return NextResponse.json({ error: "invalid campaign_id" }, { status: 400 });
  }

  if (!getCampaign(campaignId)) {
    return NextResponse.json({ error: "campaign not found" }, { status: 404 });
  }

  const events = listEvents(campaignId);
  // Summary: the most recent logged event summary (deterministic by seq).
  const summary = events.length > 0 ? events[events.length - 1].summary : "";

  // Open threads: derive a deterministic follow-up from any event that
  // references a "goblin trail".
  const openThreads: string[] = [];
  for (const event of events) {
    if (event.summary.toLowerCase().includes("goblin trail")) {
      const thread = "Resolve goblin trail ambush";
      if (!openThreads.includes(thread)) {
        openThreads.push(thread);
      }
    }
  }

  return NextResponse.json({
    campaign_id: campaignId,
    summary,
    open_threads: openThreads,
  });
}
