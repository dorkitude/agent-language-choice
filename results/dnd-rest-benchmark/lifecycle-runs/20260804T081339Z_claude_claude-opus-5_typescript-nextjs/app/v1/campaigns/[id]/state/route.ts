import { countEvents, getCampaign, listCharacters } from "../../../../../lib/campaigns";
import { json, notFound } from "../../../../../lib/http";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;
  const campaign = getCampaign(id);
  if (!campaign) return notFound("unknown campaign");

  return json({
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: listCharacters(id),
    log_count: countEvents(id),
  });
}
