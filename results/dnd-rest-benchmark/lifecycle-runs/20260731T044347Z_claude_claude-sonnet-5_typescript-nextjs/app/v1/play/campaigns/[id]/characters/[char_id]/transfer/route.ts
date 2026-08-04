import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayMemberByCharacterId, hasPlayMemberForUser, updatePlayMember } from "../../../../../store.js";

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

  const member = getPlayMemberByCharacterId(campaignId, characterId);
  if (!member) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const currentOwner = member.owner ?? member.username;
  if (username !== currentOwner) {
    return Response.json(
      { error: `only ${currentOwner} may transfer character ${characterId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { new_owner?: unknown };

  const newOwner = requireNonEmptyString(body.new_owner, "new_owner");
  if (newOwner instanceof Response) return newOwner;

  const newOwnerIsMember = newOwner === campaign.owner || hasPlayMemberForUser(campaignId, newOwner);
  if (!newOwnerIsMember) {
    return Response.json(
      { error: `${newOwner} is not a member of campaign ${campaignId}` },
      { status: 400 },
    );
  }

  updatePlayMember({ ...member, owner: newOwner });

  return Response.json({ character_id: characterId, owner: newOwner }, { status: 200 });
}
