import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignReplayEvent,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import type { CreatePlayCampaignReplayEventInput } from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.event_id) ||
    !isNonEmptyString(b.text) ||
    b.kind !== "append"
  ) {
    return badRequest();
  }

  const input: CreatePlayCampaignReplayEventInput = {
    event_id: b.event_id,
    kind: "append",
    text: b.text,
  };

  const result = createPlayCampaignReplayEvent(id, input);

  if (result === null) {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }
  if (result === "bad_request") {
    return badRequest();
  }

  return created(result);
}
