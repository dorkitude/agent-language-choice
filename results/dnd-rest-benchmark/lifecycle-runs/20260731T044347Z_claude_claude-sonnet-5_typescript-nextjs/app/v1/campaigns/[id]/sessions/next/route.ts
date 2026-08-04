import { getNextCampaignSession } from "../../../store.js";
import { requireCampaign } from "../../../http.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const session = getNextCampaignSession(campaignId);
  if (!session) {
    return Response.json(
      { error: `no sessions scheduled for campaign ${campaignId}` },
      { status: 404 },
    );
  }

  return Response.json({
    id: session.id,
    starts_at: session.starts_at,
    agenda_count: session.agenda.length,
  });
}
