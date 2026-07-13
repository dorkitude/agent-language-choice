import { NextResponse } from "next/server";
import { getCampaign, listCharacters, countEvents } from "../../store";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id: campaignId } = await ctx.params;

  const campaign = getCampaign(campaignId);
  if (!campaign) {
    return NextResponse.json({ error: "unknown campaign" }, { status: 404 });
  }

  return NextResponse.json({
    id: campaign.id,
    name: campaign.name,
    dm: campaign.dm,
    characters: listCharacters(campaignId),
    log_count: countEvents(campaignId),
  });
}
