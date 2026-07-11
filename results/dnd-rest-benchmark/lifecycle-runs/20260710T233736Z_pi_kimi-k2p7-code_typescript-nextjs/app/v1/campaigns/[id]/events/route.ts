import { addEvent } from "../../../../lib/campaign.js";

function campaignIdFromUrl(url: string): string {
  const segments = new URL(url).pathname.split("/").filter(Boolean);
  const campaignsIndex = segments.indexOf("campaigns");
  return segments[campaignsIndex + 1];
}

export async function POST(request: Request) {
  try {
    const id = campaignIdFromUrl(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    const event = addEvent(id, body);
    return Response.json(event, { status: 201 });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "campaign not found") {
      return Response.json({ error: message }, { status: 404 });
    }
    if (message === "event id already exists") {
      return Response.json({ error: message }, { status: 409 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
