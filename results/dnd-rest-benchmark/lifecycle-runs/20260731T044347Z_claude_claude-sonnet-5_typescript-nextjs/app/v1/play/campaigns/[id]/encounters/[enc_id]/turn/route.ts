import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import { getPlayEncounter, getPlayEncounterTurnOrder, hasPlayMemberForUser } from "../../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const encounter = getPlayEncounter(campaignId, encounterId);
  if (!encounter) {
    return Response.json({ error: `encounter ${encounterId} not found` }, { status: 404 });
  }

  const order = getPlayEncounterTurnOrder(encounter);
  if (order.length === 0) {
    return Response.json({ error: `encounter ${encounterId} has no combatants` }, { status: 404 });
  }

  const round = encounter.round ?? 1;
  const turnIndex = encounter.turn_index ?? 0;
  const active = order[turnIndex % order.length];

  return Response.json(
    {
      round,
      turn_index: turnIndex,
      active: { name: active.name, kind: active.kind, initiative: active.initiative },
    },
    { status: 200 },
  );
}
