import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayMember,
  hasPlayMemberCharacter,
  hasPlayMemberForUser,
  listPlayMembers,
  PlayMember,
  STARTING_GOLD,
} from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  if (session.user.role !== "player") {
    return Response.json({ error: "only a player may join a play campaign" }, { status: 403 });
  }

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { character_id, name, class: charClass } = (body ?? {}) as {
    character_id?: unknown;
    name?: unknown;
    class?: unknown;
  };

  const characterId = requireNonEmptyString(character_id, "character_id");
  if (characterId instanceof Response) return characterId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  const validClass = requireNonEmptyString(charClass, "class");
  if (validClass instanceof Response) return validClass;

  const username = session.user.username;

  if (hasPlayMemberForUser(campaignId, username)) {
    return Response.json(
      { error: `${username} already has a membership in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  if (hasPlayMemberCharacter(campaignId, characterId)) {
    return Response.json(
      { error: `character ${characterId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  if (listPlayMembers(campaignId).length >= campaign.max_players) {
    return Response.json({ error: `campaign ${campaignId} party is full` }, { status: 409 });
  }

  const member: PlayMember = {
    campaign_id: campaignId,
    username,
    character_id: characterId,
    name: validName,
    class: validClass,
    owner: username,
    gold: STARTING_GOLD,
  };
  createPlayMember(member);

  return Response.json(
    { username, character_id: characterId, name: validName, class: validClass },
    { status: 201 },
  );
}
