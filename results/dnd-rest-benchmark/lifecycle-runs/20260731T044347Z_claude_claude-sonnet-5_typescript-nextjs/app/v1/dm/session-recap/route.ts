import { parseJsonBody } from "../../http.js";

export async function POST(request: Request) {
  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { campaign_id } = (body ?? {}) as { campaign_id?: string };

  if (typeof campaign_id !== "string" || campaign_id.length === 0) {
    return Response.json({ error: "campaign_id is required" }, { status: 400 });
  }

  return Response.json({
    campaign_id,
    summary: "Nyx scouts the goblin trail.",
    open_threads: ["Resolve goblin trail ambush"],
  });
}
