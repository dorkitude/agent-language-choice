import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getContentRecord,
  updateContentTags,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidTagsPayload(
  body: Record<string, unknown>
): string[] | null {
  if (!Array.isArray(body.tags)) {
    return null;
  }

  const tags: string[] = [];
  const seen = new Set<string>();
  for (const tag of body.tags) {
    if (typeof tag !== "string" || tag.length === 0 || seen.has(tag)) {
      return null;
    }
    seen.add(tag);
    tags.push(tag);
  }

  return tags;
}

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; content_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, content_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const existing = getContentRecord(id, content_id);
  if (!existing) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const tags = isValidTagsPayload(parsed.body);
  if (tags === null) {
    return badRequest();
  }

  const result = updateContentTags(id, content_id, tags);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
