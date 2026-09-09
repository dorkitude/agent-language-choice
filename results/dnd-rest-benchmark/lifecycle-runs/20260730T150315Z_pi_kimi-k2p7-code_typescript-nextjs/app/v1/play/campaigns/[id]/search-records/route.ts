import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createSearchRecord,
  getPlayCampaign,
  getPlayCampaignMember,
  getSearchRecords,
  type CreateSearchRecordInput,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidSearchRecordPayload(
  body: Record<string, unknown>
): CreateSearchRecordInput | null {
  if (
    typeof body.record_id !== "string" ||
    body.record_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    return null;
  }
  return { record_id: body.record_id, text: body.text };
}

function parsePagination(
  url: URL
): { ok: true; q: string | null; cursor: number; limit: number } | { ok: false; response: ReturnType<typeof badRequest> } {
  const q = url.searchParams.get("q");

  const limitParam = url.searchParams.get("limit");
  let limit = 2;
  if (limitParam !== null) {
    if (!/^-?\d+$/.test(limitParam)) {
      return { ok: false, response: badRequest() };
    }
    limit = Number.parseInt(limitParam, 10);
    if (!Number.isInteger(limit) || limit < 1 || limit > 3) {
      return { ok: false, response: badRequest() };
    }
  }

  const cursorParam = url.searchParams.get("cursor");
  let cursor = 0;
  if (cursorParam !== null) {
    if (!/^\d+$/.test(cursorParam)) {
      return { ok: false, response: badRequest() };
    }
    cursor = Number.parseInt(cursorParam, 10);
    if (!Number.isInteger(cursor) || cursor < 0) {
      return { ok: false, response: badRequest() };
    }
  }

  return { ok: true, q, cursor, limit };
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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const payload = isValidSearchRecordPayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const result = createSearchRecord(id, payload);
  if (!result) {
    return badRequest();
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
  const pagination = parsePagination(url);
  if (!pagination.ok) {
    return pagination.response;
  }

  const result = getSearchRecords(
    id,
    pagination.q,
    pagination.cursor,
    pagination.limit
  );

  return ok(result);
}
