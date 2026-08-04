import { requireSession } from "../../../../../../auth/session.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayEvent,
  getNextPlayEventSequence,
  getPlayScene,
  updatePlayScene,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; scene_id: string }> },
) {
  const { id: campaignId, scene_id: sceneId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may close a scene",
  );
  if (ownerCheck) return ownerCheck;

  const scene = getPlayScene(campaignId, sceneId);
  if (!scene) {
    return Response.json({ error: `scene ${sceneId} not found` }, { status: 404 });
  }

  const closed = { ...scene, status: "closed" as const };
  updatePlayScene(closed);

  const sequence = getNextPlayEventSequence(campaignId);
  createPlayEvent(campaignId, {
    sequence,
    kind: "scene",
    actor: session.user.username,
    text: `Closed ${closed.name}`,
  });

  return Response.json({ id: closed.id, status: closed.status }, { status: 200 });
}
