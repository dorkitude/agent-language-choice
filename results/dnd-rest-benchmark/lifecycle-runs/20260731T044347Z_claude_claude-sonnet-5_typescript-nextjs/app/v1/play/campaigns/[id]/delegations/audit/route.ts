import { requireSession } from "../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../http.js";
import { listPlayDelegationAuditEntries } from "../../../../store.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign owner may read delegation audit",
  );
  if (ownerCheck) return ownerCheck;

  const entries = listPlayDelegationAuditEntries(campaignId);

  return Response.json({ entries }, { status: 200 });
}
