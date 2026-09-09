import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  notFound,
  ok,
  parseJsonBody,
  forbidden,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  updatePlayCampaignQuestState,
} from "../../../../../../../lib/storage.js";
import type { PlayCampaignQuestState } from "../../../../../../../lib/types.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, quest_id } = await params;
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (b.state !== "active" && b.state !== "completed") {
    return badRequest();
  }
  const state = b.state as PlayCampaignQuestState;

  const result = updatePlayCampaignQuestState(id, quest_id, state);
  if (result === null) {
    return notFound();
  }
  if (result === "bad_request") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return ok(result);
}
