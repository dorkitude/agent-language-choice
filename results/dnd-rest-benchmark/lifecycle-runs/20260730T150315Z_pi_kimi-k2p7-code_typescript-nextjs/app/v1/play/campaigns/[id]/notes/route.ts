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
  createNote,
  getNotes,
  getPlayCampaign,
  getPlayCampaignMember,
  type CreateNoteInput,
  type UpdateNoteInput,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function isValidNotePayload(
  body: Record<string, unknown>
): CreateNoteInput | null {
  if (
    typeof body.note_id !== "string" ||
    body.note_id.length === 0 ||
    typeof body.text !== "string" ||
    body.text.length === 0
  ) {
    return null;
  }

  if (body.visibility !== "private" && body.visibility !== "party") {
    return null;
  }

  return {
    note_id: body.note_id,
    text: body.text,
    visibility: body.visibility,
  };
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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const payload = isValidNotePayload(parsed.body);
  if (!payload) {
    return badRequest();
  }

  const result = createNote(id, auth.user.username, payload);
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

  const isDm = campaign.owner === auth.user.username;
  const notes = getNotes(id);

  const visibleNotes = isDm
    ? notes
    : notes.filter(
        (note) =>
          note.visibility === "party" || note.owner === auth.user.username
      );

  return ok({ notes: visibleNotes });
}
