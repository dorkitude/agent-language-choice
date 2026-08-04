import { requireSession } from "../../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../../http.js";
import { getPlayEncounter, getPlayEncounterTurnOrder } from "../../../../../../store.js";

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

  const turnIndex = (encounter.turn_index ?? 0) % order.length;
  const active = order[turnIndex];

  const username = session.user.username;
  const isCurrentCombatant = active.kind === "player" && active.member === username;
  if (!isCurrentCombatant) {
    return Response.json(
      { error: `${username} may not ready an action out of order` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const { trigger } = (parsed.body ?? {}) as { trigger?: unknown };

  const validTrigger = requireNonEmptyString(trigger, "trigger");
  if (validTrigger instanceof Response) return validTrigger;

  return Response.json({ actor: username, trigger: validTrigger }, { status: 201 });
}
