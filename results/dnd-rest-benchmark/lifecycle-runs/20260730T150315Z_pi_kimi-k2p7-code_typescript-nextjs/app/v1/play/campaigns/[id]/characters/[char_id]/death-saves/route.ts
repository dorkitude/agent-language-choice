import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMemberState,
  recordDeathSave,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, char_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const state = getPlayCampaignMemberState(id, char_id);
  if (!state) {
    return notFound();
  }

  if (state.username !== auth.user.username) {
    return forbidden();
  }

  if (state.status !== "unconscious") {
    return conflict();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const outcome = parsed.body.outcome;
  if (outcome !== "success" && outcome !== "failure") {
    return badRequest();
  }

  const result = recordDeathSave(id, char_id, outcome);
  if (!result) {
    return conflict();
  }

  return created(result);
}
