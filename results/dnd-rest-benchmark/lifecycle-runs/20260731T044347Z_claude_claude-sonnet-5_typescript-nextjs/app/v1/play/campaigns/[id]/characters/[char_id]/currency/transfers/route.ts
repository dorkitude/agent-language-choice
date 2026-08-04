import { requireSession } from "../../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import {
  createPlayCurrencyTransfer,
  getNextPlayTransferId,
  getPlayMemberByCharacterId,
  STARTING_GOLD,
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

  const source = getPlayMemberByCharacterId(campaignId, characterId);
  if (!source) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const username = session.user.username;
  const sourceOwner = source.owner ?? source.username;
  if (username !== sourceOwner) {
    return Response.json(
      { error: `only ${sourceOwner} may transfer gold from character ${characterId}` },
      { status: 403 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { to_character_id?: unknown; gold?: unknown };

  const toCharacterId = body.to_character_id;
  if (typeof toCharacterId !== "string" || toCharacterId.length === 0) {
    return Response.json({ error: "to_character_id must be a non-empty string" }, { status: 400 });
  }

  if (toCharacterId === characterId) {
    return Response.json(
      { error: "to_character_id must be a different character than the source" },
      { status: 400 },
    );
  }

  const gold = body.gold;
  if (typeof gold !== "number" || !Number.isFinite(gold) || gold <= 0) {
    return Response.json({ error: "gold must be a positive number" }, { status: 400 });
  }

  const destination = getPlayMemberByCharacterId(campaignId, toCharacterId);
  if (!destination) {
    return Response.json(
      { error: `character ${toCharacterId} not found in campaign ${campaignId}` },
      { status: 400 },
    );
  }

  const sourceGold = source.gold ?? STARTING_GOLD;
  if (sourceGold < gold) {
    return Response.json(
      { error: `character ${characterId} has insufficient gold` },
      { status: 409 },
    );
  }

  const destinationGold = destination.gold ?? STARTING_GOLD;
  const fromGold = sourceGold - gold;
  const toGold = destinationGold + gold;

  updatePlayMember({ ...source, gold: fromGold });
  updatePlayMember({ ...destination, gold: toGold });

  const transferId = getNextPlayTransferId(campaignId);
  createPlayCurrencyTransfer({
    campaign_id: campaignId,
    transfer_id: transferId,
    from_character_id: characterId,
    to_character_id: toCharacterId,
    gold,
  });

  return Response.json(
    {
      from_character_id: characterId,
      to_character_id: toCharacterId,
      gold,
      from_gold: fromGold,
      to_gold: toGold,
      transfer_id: transferId,
    },
    { status: 201 },
  );
}
