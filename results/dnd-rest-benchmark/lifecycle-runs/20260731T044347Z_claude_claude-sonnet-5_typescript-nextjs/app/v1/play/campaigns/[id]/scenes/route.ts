import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import { createPlayScene, hasPlayScene, PlayScene } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may create a scene",
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

  if (hasPlayScene(campaignId, validId)) {
    return Response.json({ error: `scene ${validId} already exists` }, { status: 409 });
  }

  const scene: PlayScene = {
    campaign_id: campaignId,
    id: validId,
    name: validName,
    status: "open",
  };
  createPlayScene(scene);

  return Response.json({ id: scene.id, name: scene.name, status: scene.status }, { status: 201 });
}
