import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayClue,
  getPlayMemberForUser,
  hasPlayClue,
  hasPlayMemberCharacter,
  listPlayClues,
  PlayClue,
  PlayClueAudience,
} from "../../../store.js";

const VALID_AUDIENCES: PlayClueAudience[] = ["character", "party", "hidden"];

function serializeClue(clue: PlayClue) {
  if (clue.audience === "character") {
    return {
      clue_id: clue.clue_id,
      text: clue.text,
      audience: clue.audience,
      character_id: clue.character_id,
    };
  }
  return {
    clue_id: clue.clue_id,
    text: clue.text,
    audience: clue.audience,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create clues",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    clue_id?: unknown;
    text?: unknown;
    audience?: unknown;
    character_id?: unknown;
  };

  const validClueId = requireNonEmptyString(body.clue_id, "clue_id");
  if (validClueId instanceof Response) return validClueId;

  const validText = requireNonEmptyString(body.text, "text");
  if (validText instanceof Response) return validText;

  const { audience, character_id: characterId } = body;
  if (typeof audience !== "string" || !VALID_AUDIENCES.includes(audience as PlayClueAudience)) {
    return Response.json(
      { error: "audience must be exactly character, party, or hidden" },
      { status: 400 },
    );
  }

  if (audience === "character") {
    if (typeof characterId !== "string" || characterId.length === 0) {
      return Response.json(
        { error: "character_id is required when audience is character" },
        { status: 400 },
      );
    }
    if (!hasPlayMemberCharacter(campaignId, characterId)) {
      return Response.json(
        { error: `campaign character ${characterId} not found` },
        { status: 400 },
      );
    }
  } else if (characterId !== undefined) {
    return Response.json(
      { error: "character_id must be omitted unless audience is character" },
      { status: 400 },
    );
  }

  if (hasPlayClue(campaignId, validClueId)) {
    return Response.json(
      { error: `clue ${validClueId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const clue: PlayClue = {
    clue_id: validClueId,
    text: validText,
    audience: audience as PlayClueAudience,
    ...(audience === "character" ? { character_id: characterId as string } : {}),
  };

  createPlayClue(campaignId, clue);

  return Response.json(serializeClue(clue), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const member = isDm ? undefined : getPlayMemberForUser(campaignId, username);
  const isMember = isDm || member !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const allClues = listPlayClues(campaignId);
  const visibleClues = isDm
    ? allClues
    : allClues.filter(
        (clue) =>
          clue.audience === "party" ||
          (clue.audience === "character" && clue.character_id === member?.character_id),
      );

  return Response.json({ clues: visibleClues.map(serializeClue) }, { status: 200 });
}
