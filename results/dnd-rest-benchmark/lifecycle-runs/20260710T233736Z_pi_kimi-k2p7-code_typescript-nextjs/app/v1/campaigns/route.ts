import { createCampaign } from "../../lib/campaign.js";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const campaign = createCampaign(body);
    return Response.json(campaign, { status: 201 });
  } catch (error) {
    if (error instanceof SyntaxError) {
      return Response.json({ error: "invalid json" }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : "invalid request";
    if (message === "campaign id already exists") {
      return Response.json({ error: message }, { status: 409 });
    }
    return Response.json({ error: message }, { status: 400 });
  }
}
