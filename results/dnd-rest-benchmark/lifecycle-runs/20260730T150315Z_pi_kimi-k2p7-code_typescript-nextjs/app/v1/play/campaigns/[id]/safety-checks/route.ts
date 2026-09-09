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
  createPlayCampaignSafetyCheck,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import type { CreatePlayCampaignSafetyCheckInput } from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

function isValidSafetyCheckTags(value: unknown): value is string[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string" || item.length === 0) return false;
    if (seen.has(item)) return false;
    seen.add(item);
  }
  return true;
}

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
    (b.kind !== "narration" && b.kind !== "chat") ||
    !isValidSafetyCheckTags(b.tags)
  ) {
    return badRequest();
  }

  const input: CreatePlayCampaignSafetyCheckInput = {
    event_id: b.event_id,
    kind: b.kind,
    text: b.text,
    tags: b.tags,
  };

  const result = createPlayCampaignSafetyCheck(id, input);
  if (result === null) {
    return notFound();
  }
  if (result === "duplicate" || result === "blocked") {
    return conflict();
  }

  return created(result);
}
