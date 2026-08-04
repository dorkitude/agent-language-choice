import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayEvent,
  getNextPlayEventSequence,
  getPlayEncounter,
  getPlayEncounterTurnOrder,
} from "../../../../../store.js";

const VALID_TYPES = new Set(["attack", "help", "dodge", "ready"]);

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

  const turnIndex = encounter.turn_index ?? 0;
  const active = order[turnIndex % order.length];

  const username = session.user.username;
  const isCurrentCombatant = active.kind === "player" && active.member === username;
  if (!isCurrentCombatant) {
    return Response.json(
      { error: `it is not ${username}'s turn to act` },
      { status: 409 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { type, target, text } = (body ?? {}) as {
    type?: unknown;
    target?: unknown;
    text?: unknown;
  };

  const validType = requireNonEmptyString(type, "type");
  if (validType instanceof Response) return validType;

  if (!VALID_TYPES.has(validType)) {
    return Response.json(
      { error: `type must be one of attack, help, dodge, ready` },
      { status: 400 },
    );
  }

  const validText = requireNonEmptyString(text, "text");
  if (validText instanceof Response) return validText;

  let validTarget: string | undefined;
  if (target !== undefined) {
    const checkedTarget = requireNonEmptyString(target, "target");
    if (checkedTarget instanceof Response) return checkedTarget;
    validTarget = checkedTarget;
  }

  const sequence = getNextPlayEventSequence(campaignId);
  const event = createPlayEvent(campaignId, {
    sequence,
    kind: "combat_action",
    actor: username,
    type: validType,
    target: validTarget,
    text: validText,
  });

  return Response.json(
    {
      sequence: event.sequence,
      kind: event.kind,
      actor: event.actor,
      type: event.type,
      target: event.target,
      text: event.text,
    },
    { status: 201 },
  );
}
