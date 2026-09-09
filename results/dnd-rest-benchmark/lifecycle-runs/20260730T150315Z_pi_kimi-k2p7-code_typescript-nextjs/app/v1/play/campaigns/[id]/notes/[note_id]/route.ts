import { requireBearerAuth } from "../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../lib/http.js";
import {
  getNote,
  getPlayCampaign,
  getPlayCampaignMember,
  updateNote,
  type UpdateNoteInput,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidUpdatePayload(
  body: Record<string, unknown>
): UpdateNoteInput | null {
  if (
    typeof body.text !== "string" ||
    body.text.length === 0 ||
    (body.visibility !== "private" && body.visibility !== "party")
  ) {
    return null;
  }

  return {
    text: body.text,
    visibility: body.visibility,
  };
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; note_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, note_id } = await params;

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

  const note = getNote(id, note_id);
  if (!note) {
    return notFound();
  }

  const isDm = campaign.owner === auth.user.username;
  if (!isDm && note.visibility === "private" && note.owner !== auth.user.username) {
    return forbidden();
  }

  return ok(note);
}

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; note_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, note_id } = await params;

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

  const note = getNote(id, note_id);
  if (!note) {
    return notFound();
  }

  if (note.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const payload = isValidUpdatePayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const result = updateNote(id, note_id, auth.user.username, payload);
  if (!result) {
    return notFound();
  }

  return ok(result);
}
