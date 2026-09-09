import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createContentRecord,
  getContentRecords,
  getPlayCampaign,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidContentPayload(
  body: Record<string, unknown>
): { content_id: string; kind: string; text: string; tags: string[] } | null {
  if (
    typeof body.content_id !== "string" ||
    body.content_id.length === 0 ||
    typeof body.kind !== "string" ||
    body.kind.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    return null;
  }

  if (!Array.isArray(body.tags) || body.tags.length === 0) {
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

  return {
    content_id: body.content_id,
    kind: body.kind,
    text: body.text,
    tags,
  };
}

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
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

  const payload = isValidContentPayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const result = createContentRecord(id, payload);
  if (!result) {
    return conflict();
  }

  return created(result);
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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const url = new URL(req.url);
  const excludeTag = url.searchParams.get("exclude_tag");
  if (excludeTag !== null && excludeTag.length === 0) {
    return badRequest();
  }

  const records = getContentRecords(id);

  const isDm = campaign.owner === auth.user.username;
  if (excludeTag !== null && !isDm) {
    return ok({
      content: records.filter((record) => !record.tags.includes(excludeTag)),
    });
  }

  return ok({ content: records });
}
