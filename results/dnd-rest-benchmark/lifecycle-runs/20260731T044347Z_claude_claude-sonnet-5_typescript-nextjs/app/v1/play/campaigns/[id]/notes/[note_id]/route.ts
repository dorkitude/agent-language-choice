import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";
import { requirePlayCampaign } from "../../../../http.js";
import {
  getPlayMemberForUser,
  getPlayNote,
  PlayNote,
  PlayNoteVisibility,
  updatePlayNote,
} from "../../../../store.js";

const VALID_VISIBILITIES: PlayNoteVisibility[] = ["private", "party"];

function serializeNote(note: PlayNote) {
  return {
    note_id: note.note_id,
    text: note.text,
    visibility: note.visibility,
    owner: note.owner,
  };
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; note_id: string }> },
) {
  const { id: campaignId, note_id: noteId } = await params;

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

  const note = getPlayNote(campaignId, noteId);
  if (!note) {
    return Response.json(
      { error: `note ${noteId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (!isDm && note.visibility === "private" && note.owner !== username) {
    return Response.json({ error: `note ${noteId} is private` }, { status: 403 });
  }

  return Response.json(serializeNote(note), { status: 200 });
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; note_id: string }> },
) {
  const { id: campaignId, note_id: noteId } = await params;

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

  const note = getPlayNote(campaignId, noteId);
  if (!note) {
    return Response.json(
      { error: `note ${noteId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (note.owner !== username) {
    return Response.json(
      { error: `only the owner of note ${noteId} may update it` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { text?: unknown; visibility?: unknown };

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  if (
    typeof body.visibility !== "string" ||
    !VALID_VISIBILITIES.includes(body.visibility as PlayNoteVisibility)
  ) {
    return Response.json({ error: "visibility must be exactly private or party" }, { status: 400 });
  }

  const updated: PlayNote = {
    ...note,
    text: validText,
    visibility: body.visibility as PlayNoteVisibility,
  };
  updatePlayNote(campaignId, updated);

  return Response.json(serializeNote(updated), { status: 200 });
}
