import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayNpcDialogueEntry,
  getPlayMemberForUser,
  getPlayNpc,
  hasPlayNpcDialogueEntry,
  listPlayNpcDialogueEntries,
} from "../../../../../store.js";
import type { PlayNpcDialogueEntry } from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> },
) {
  const { id: campaignId, npc_id: npcId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may append npc dialogue",
  );
  if (ownerCheck) return ownerCheck;

  const npc = getPlayNpc(campaignId, npcId);
  if (!npc) {
    return Response.json({ error: `npc ${npcId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    dialogue_id?: unknown;
    speaker?: unknown;
    text?: unknown;
    visibility?: unknown;
  };

  const validDialogueId = requireNonEmptyString(body.dialogue_id, "dialogue_id");
  if (validDialogueId instanceof Response) return validDialogueId;

  const validSpeaker = requireNonEmptyString(body.speaker, "speaker");
  if (validSpeaker instanceof Response) return validSpeaker;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  if (body.visibility !== "public" && body.visibility !== "private") {
    return Response.json(
      { error: "visibility must be exactly 'public' or 'private'" },
      { status: 400 },
    );
  }

  if (hasPlayNpcDialogueEntry(campaignId, npcId, validDialogueId)) {
    return Response.json(
      { error: `dialogue ${validDialogueId} already exists for npc ${npcId}` },
      { status: 409 },
    );
  }

  const entry = createPlayNpcDialogueEntry(campaignId, npcId, {
    dialogue_id: validDialogueId,
    speaker: validSpeaker,
    text: validText,
    visibility: body.visibility,
  });

  return Response.json(
    {
      dialogue_id: entry.dialogue_id,
      speaker: entry.speaker,
      text: entry.text,
      visibility: entry.visibility,
    },
    { status: 201 },
  );
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> },
) {
  const { id: campaignId, npc_id: npcId } = await params;

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

  const npc = getPlayNpc(campaignId, npcId);
  if (!npc) {
    return Response.json({ error: `npc ${npcId} not found` }, { status: 404 });
  }

  const allEntries = listPlayNpcDialogueEntries(campaignId, npcId);
  const entries = isDm
    ? allEntries
    : allEntries.filter((entry: PlayNpcDialogueEntry) => entry.visibility === "public");

  return Response.json(
    {
      npc_id: npcId,
      entries: entries.map((entry: PlayNpcDialogueEntry) => ({
        dialogue_id: entry.dialogue_id,
        speaker: entry.speaker,
        text: entry.text,
        visibility: entry.visibility,
      })),
    },
    { status: 200 },
  );
}
