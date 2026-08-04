import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, hasPlayMemberForUser } from "../../../../../store.js";

const DEFAULT_HP_MAX = 20;

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
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const hpMax = member.hp_max ?? DEFAULT_HP_MAX;
  const hpCurrent = member.hp_current ?? hpMax;
  const status = member.status ?? "conscious";

  return Response.json(
    { character_id: characterId, hp_current: hpCurrent, hp_max: hpMax, status },
    { status: 200 },
  );
}
