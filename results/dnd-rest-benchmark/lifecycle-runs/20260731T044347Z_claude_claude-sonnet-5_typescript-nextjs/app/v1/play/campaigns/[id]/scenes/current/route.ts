import { requireSession } from "../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../http.js";
import { getPlayScene, hasPlayMemberForUser } from "../../../../store.js";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const sceneId = campaign.current_scene_id;
  const scene = sceneId ? getPlayScene(campaignId, sceneId) : undefined;
  if (!scene || scene.status !== "open") {
    return Response.json({ error: `campaign ${campaignId} has no current scene` }, { status: 404 });
  }

  return Response.json({ id: scene.id, name: scene.name, status: scene.status }, { status: 200 });
}
