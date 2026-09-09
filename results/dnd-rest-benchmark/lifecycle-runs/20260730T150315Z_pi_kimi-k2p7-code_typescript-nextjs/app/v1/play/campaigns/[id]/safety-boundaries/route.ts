import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignSafetyBoundaries,
  replacePlayCampaignSafetyBoundaries,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidBlockedTags(value: unknown): value is string[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string" || item.length === 0) return false;
    if (seen.has(item)) return false;
    seen.add(item);
  }
  return true;
}

export async function PUT(
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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (!isValidBlockedTags(b.blocked_tags)) {
    return badRequest();
  }

  const result = replacePlayCampaignSafetyBoundaries(id, b.blocked_tags);
  if (!result) {
    return notFound();
  }

  return ok(result);
}

export async function GET(
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

  const result = getPlayCampaignSafetyBoundaries(id);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
