import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayWhisper,
  getPlayMemberByOwner,
  getPlayMemberForUser,
  hasPlayMemberCharacter,
  hasPlayWhisper,
  listPlayWhispers,
  PlayWhisper,
} from "../../../store.js";

function serializeWhisper(whisper: PlayWhisper) {
  return {
    whisper_id: whisper.whisper_id,
    from_character_id: whisper.from_character_id,
    to_character_id: whisper.to_character_id,
    text: whisper.text,
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

  const senderMember = getPlayMemberByOwner(campaignId, username);
  if (!senderMember) {
    return Response.json(
      { error: `${username} does not own a character in campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    whisper_id?: unknown;
    to_character_id?: unknown;
    text?: unknown;
  };

  const validWhisperId = requireNonEmptyString(body.whisper_id, "whisper_id");
  if (validWhisperId instanceof Response) return validWhisperId;

  const validToCharacterId = requireNonEmptyString(body.to_character_id, "to_character_id");
  if (validToCharacterId instanceof Response) return validToCharacterId;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  if (!hasPlayMemberCharacter(campaignId, validToCharacterId)) {
    return Response.json(
      { error: `character ${validToCharacterId} is not a member of campaign ${campaignId}` },
      { status: 400 },
    );
  }

  if (hasPlayWhisper(campaignId, validWhisperId)) {
    return Response.json(
      { error: `whisper ${validWhisperId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const whisper: PlayWhisper = {
    whisper_id: validWhisperId,
    from_character_id: senderMember.character_id,
    to_character_id: validToCharacterId,
    text: validText,
  };

  createPlayWhisper(campaignId, whisper);

  return Response.json(serializeWhisper(whisper), { status: 201 });
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

  const allWhispers = listPlayWhispers(campaignId);
  if (isDm) {
    return Response.json({ whispers: allWhispers.map(serializeWhisper) }, { status: 200 });
  }

  const ownedCharacterId = getPlayMemberByOwner(campaignId, username)?.character_id;
  const visibleWhispers = allWhispers.filter(
    (whisper) =>
      whisper.from_character_id === ownedCharacterId || whisper.to_character_id === ownedCharacterId,
  );

  return Response.json({ whispers: visibleWhispers.map(serializeWhisper) }, { status: 200 });
}
