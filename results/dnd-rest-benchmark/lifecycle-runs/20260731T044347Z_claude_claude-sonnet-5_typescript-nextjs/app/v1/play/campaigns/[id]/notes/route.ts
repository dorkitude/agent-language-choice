import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayNote,
  getPlayMemberForUser,
  hasPlayNote,
  listPlayNotes,
  PlayNote,
  PlayNoteVisibility,
} from "../../../store.js";

const VALID_VISIBILITIES: PlayNoteVisibility[] = ["private", "party"];

function serializeNote(note: PlayNote) {
  return {
    note_id: note.note_id,
    text: note.text,
    visibility: note.visibility,
    owner: note.owner,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    note_id?: unknown;
    text?: unknown;
    visibility?: unknown;
  };

  const validNoteId = requireNonEmptyString(body.note_id, "note_id");
  if (validNoteId instanceof Response) return validNoteId;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  if (
    typeof body.visibility !== "string" ||
    !VALID_VISIBILITIES.includes(body.visibility as PlayNoteVisibility)
  ) {
    return Response.json({ error: "visibility must be exactly private or party" }, { status: 400 });
  }

  if (hasPlayNote(campaignId, validNoteId)) {
    return Response.json(
      { error: `note ${validNoteId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const note: PlayNote = {
    note_id: validNoteId,
    text: validText,
    visibility: body.visibility as PlayNoteVisibility,
    owner: username,
  };

  createPlayNote(campaignId, note);

  return Response.json(serializeNote(note), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const allNotes = listPlayNotes(campaignId);
  const visibleNotes = isDm
    ? allNotes
    : allNotes.filter((note) => note.visibility === "party" || note.owner === username);

  return Response.json({ notes: visibleNotes.map(serializeNote) }, { status: 200 });
}
