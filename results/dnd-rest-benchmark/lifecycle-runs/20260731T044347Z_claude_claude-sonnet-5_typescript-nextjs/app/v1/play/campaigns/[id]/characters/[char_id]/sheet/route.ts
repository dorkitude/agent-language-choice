import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, getPlayMemberForUser } from "../../../../../store.js";

const BASIC_SHEET_LEVEL = 1;
const BASIC_SHEET_PROFICIENCY_BONUS = 2;
const BASIC_SHEET_HP_MAX = 10;
const BASIC_SHEET_ARMOR_CLASS = 10;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; char_id: string }> },
) {
  const { id: campaignId, char_id: characterId } = await params;

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

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const owner = member.owner ?? member.username;
  if (!isDm && owner !== username) {
    return Response.json(
      { error: `only the owner of character ${characterId} may read its sheet` },
      { status: 403 },
    );
  }

  return Response.json(
    {
      character_id: characterId,
      owner,
      name: member.name,
      class: member.class,
      level: BASIC_SHEET_LEVEL,
      proficiency_bonus: BASIC_SHEET_PROFICIENCY_BONUS,
      hp_max: BASIC_SHEET_HP_MAX,
      armor_class: BASIC_SHEET_ARMOR_CLASS,
    },
    { status: 200 },
  );
}
