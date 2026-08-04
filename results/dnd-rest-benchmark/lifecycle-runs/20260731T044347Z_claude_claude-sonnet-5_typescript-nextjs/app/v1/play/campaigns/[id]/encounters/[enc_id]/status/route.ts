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
  const round = encounter.round ?? 1;
  const turnIndex = encounter.turn_index ?? 0;
  const active = order.length > 0 ? order[turnIndex % order.length] : null;

  return Response.json(
    {
      round,
      turn_index: turnIndex,
      active: active
        ? { name: active.name, kind: active.kind, initiative: active.initiative, target: active.target }
        : null,
      order: order.map((entry) => ({
        name: entry.name,
        kind: entry.kind,
        initiative: entry.initiative,
        target: entry.target,
      })),
      conditions: encounter.conditions ?? {},
    },
    { status: 200 },
  );
}
