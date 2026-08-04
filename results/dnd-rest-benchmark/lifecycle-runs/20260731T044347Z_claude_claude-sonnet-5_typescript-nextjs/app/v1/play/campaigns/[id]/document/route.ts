import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody } from "../../../../http.js";
import { updatePlayCampaign } from "../../../store.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const story = campaign.story ?? "";

  if (session.user.username === campaign.owner) {
    return Response.json({ story, dm_notes: campaign.dm_notes ?? "" }, { status: 200 });
  }

  return Response.json({ story }, { status: 200 });
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may update the campaign document",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { story, dm_notes } = (body ?? {}) as { story?: unknown; dm_notes?: unknown };

  if (typeof story !== "string") {
    return Response.json({ error: "story must be a string" }, { status: 400 });
  }

  if (typeof dm_notes !== "string") {
    return Response.json({ error: "dm_notes must be a string" }, { status: 400 });
  }

  updatePlayCampaign({ ...campaign, story, dm_notes });

  return Response.json({ story, dm_notes }, { status: 200 });
}
