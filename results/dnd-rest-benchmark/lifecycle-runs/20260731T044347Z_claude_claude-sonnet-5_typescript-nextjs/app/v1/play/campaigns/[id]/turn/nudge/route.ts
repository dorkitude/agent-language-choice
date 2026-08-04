import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import { updatePlayCampaign } from "../../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const ownerCheck = requireCampaignOwner(campaign, username, "only the campaign owner may send a turn nudge");
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { message } = (body ?? {}) as { message?: unknown };

  const validMessage = requireNonEmptyString(message, "message");
  if (validMessage instanceof Response) return validMessage;

  const nudgeCount = (campaign.nudge_count ?? 0) + 1;

  updatePlayCampaign({
    ...campaign,
    nudge_count: nudgeCount,
  });

  return Response.json(
    {
      actor: username,
      target: campaign.current_actor ?? null,
      message: validMessage,
      nudge_count: nudgeCount,
    },
    { status: 201 },
  );
}
