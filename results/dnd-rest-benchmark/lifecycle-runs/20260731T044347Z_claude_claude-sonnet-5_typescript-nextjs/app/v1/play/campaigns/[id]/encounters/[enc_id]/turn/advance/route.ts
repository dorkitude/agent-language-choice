import { requireSession } from "../../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import { getPlayEncounter, getPlayEncounterTurnOrder, updatePlayEncounter } from "../../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; enc_id: string }> },
) {
  const { id: campaignId, enc_id: encounterId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

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

  const username = session.user.username;
  const isCurrentCombatant = active.kind === "player" && active.member === username;
  const isOwner = username === campaign.owner;
  if (!isOwner && !isCurrentCombatant) {
    return Response.json(
      { error: `${username} may not advance the turn out of order` },
      { status: 409 },
    );
  }

  let nextIndex = turnIndex + 1;
  let nextRound = round;
  if (nextIndex >= order.length) {
    nextIndex = 0;
    nextRound += 1;
  }

  const nextActive = order[nextIndex];

  const conditions = encounter.conditions ?? {};
  const targetConditions = conditions[nextActive.target];
  const nextConditions =
    targetConditions && targetConditions.length > 0
      ? {
          ...conditions,
          [nextActive.target]: targetConditions
            .map((entry) => ({ ...entry, remaining_rounds: entry.remaining_rounds - 1 }))
            .filter((entry) => entry.remaining_rounds > 0),
        }
      : conditions;

  updatePlayEncounter({
    ...encounter,
    round: nextRound,
    turn_index: nextIndex,
    conditions: nextConditions,
  });

  return Response.json(
    {
      round: nextRound,
      turn_index: nextIndex,
      active: { name: nextActive.name, kind: nextActive.kind, initiative: nextActive.initiative },
    },
    { status: 200 },
  );
}
