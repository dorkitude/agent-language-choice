import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getScene,
  setCurrentScene,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; scene_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, scene_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const scene = getScene(id, scene_id);
  if (!scene) {
    return notFound();
  }

  if (scene.status !== "open") {
    return badRequest();
  }

  const result = setCurrentScene(id, scene_id, auth.user.username);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
