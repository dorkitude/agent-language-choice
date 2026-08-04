import { requireSession } from "../../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import {
  getPlayMemberByCharacterId,
  hasPlayMemberForUser,
  updatePlayMember,
} from "../../../../../../store.js";

export async function POST(
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

  let concentration = member.concentration ?? null;
  if (concentration) {
    const remainingTurns = concentration.remaining_turns - 1;
    concentration = remainingTurns > 0 ? { ...concentration, remaining_turns: remainingTurns } : null;
    updatePlayMember({ ...member, concentration });
  }

  return Response.json(
    { character_id: characterId, concentration },
    { status: 200 },
  );
}
