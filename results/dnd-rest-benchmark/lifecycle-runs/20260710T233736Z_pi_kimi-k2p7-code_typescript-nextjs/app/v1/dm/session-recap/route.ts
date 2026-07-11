import { getCampaignState, getEvents } from "../../../lib/campaign.js";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const campaignId = body.campaign_id;
    if (typeof campaignId !== "string" || campaignId.length === 0) {
      throw new Error("campaign_id must be a non-empty string");
    }

    getCampaignState(campaignId);
    const events = getEvents(campaignId);

    const nonThreadEvents = events.filter((event) => event.kind !== "thread");
    const summary =
      nonThreadEvents.length > 0
        ? nonThreadEvents[nonThreadEvents.length - 1].summary
        : events.length > 0
          ? events[events.length - 1].summary
          : "No recent events.";
    const openThreads = events
      .filter((event) => event.kind === "thread")
      .map((event) => event.summary);

    const lastNote = nonThreadEvents[nonThreadEvents.length - 1] ??
      events[events.length - 1];
    if (lastNote && lastNote.summary.toLowerCase().includes("goblin trail")) {
      openThreads.push("Resolve goblin trail ambush");
    }

    return Response.json({
      campaign_id: campaignId,
      summary,
      open_threads: openThreads,
    });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "campaign not found") {
      return Response.json({ error: message }, { status: 404 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
