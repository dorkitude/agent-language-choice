import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  getPlayLoot,
  hasPlayMemberCharacter,
  hasPlayMemberForUser,
  updatePlayLoot,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; loot_id: string }> },
) {
  const { id: campaignId, loot_id: lootId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  if (!hasPlayMemberForUser(campaignId, username)) {
    return Response.json(
      { error: `only authenticated campaign players may vote on loot` },
      { status: 403 },
    );
  }

  const loot = getPlayLoot(campaignId, lootId);
  if (!loot) {
    return Response.json(
      { error: `loot ${lootId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { recipient_character_id?: unknown };

  const validRecipient = requireNonEmptyString(body.recipient_character_id, "recipient_character_id");
  if (validRecipient instanceof Response) return validRecipient;

  if (!hasPlayMemberCharacter(campaignId, validRecipient)) {
    return Response.json(
      { error: `character ${validRecipient} not found in campaign ${campaignId}` },
      { status: 400 },
    );
  }

  if (loot.votes.some((vote) => vote.voter === username)) {
    return Response.json(
      { error: `${username} has already voted on loot ${lootId}` },
      { status: 409 },
    );
  }

  const votes = [...loot.votes, { voter: username, recipient_character_id: validRecipient }];
  const updated = updatePlayLoot({ ...loot, votes });

  const votesForRecipient = updated.votes.filter(
    (vote) => vote.recipient_character_id === validRecipient,
  ).length;

  return Response.json(
    {
      loot_id: updated.loot_id,
      voter: username,
      recipient_character_id: validRecipient,
      votes_for_recipient: votesForRecipient,
    },
    { status: 201 },
  );
}
