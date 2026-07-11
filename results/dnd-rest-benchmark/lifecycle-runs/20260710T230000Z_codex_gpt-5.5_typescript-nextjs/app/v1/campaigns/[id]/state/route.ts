import { json } from "../../../../api.js";
import { campaignCharacters, campaignEvents, campaigns } from "../../state.js";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { id } = await context.params;
  const campaign = campaigns.get(id);
  if (campaign === undefined) {
    return json({ error: "not_found" }, 404);
  }

  return json({
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: campaignCharacters.list(id),
    log_count: campaignEvents.count(id),
  });
}
