import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import { createPlayLocation, hasPlayLocation, PlayLocation } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may create a location",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name } = (body ?? {}) as { id?: unknown; name?: unknown };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  if (hasPlayLocation(campaignId, validId)) {
    return Response.json({ error: `location ${validId} already exists` }, { status: 409 });
  }

  const location: PlayLocation = {
    campaign_id: campaignId,
    id: validId,
    name: validName,
  };
  createPlayLocation(location);

  return Response.json({ id: location.id, name: location.name }, { status: 201 });
}
