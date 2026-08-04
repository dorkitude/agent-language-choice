import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import {
  createPlayEvent,
  getNextPlayEventSequence,
  listPlayMembers,
  updatePlayCampaign,
} from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const currentActor = campaign.current_actor ?? null;

  // Only the owning dm may resolve, and only once the queue has actually
  // handed the turn to them (i.e. after a player's action moved current_actor
  // to the owner). This mirrors the inverse check in POST /actions.
  if (username !== campaign.owner || currentActor !== campaign.owner) {
    return Response.json({ error: "it is not your turn to resolve" }, { status: 409 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { text } = (body ?? {}) as { text?: unknown };

  const validText = requireNonEmptyString(text, "text");
  if (validText instanceof Response) return validText;

  const sequence = getNextPlayEventSequence(campaignId);
  const event = createPlayEvent(campaignId, {
    sequence,
    kind: "resolution",
    actor: username,
    text: validText,
  });

  // Advance turn order in party-join order (not initiative order, and not
  // by re-deriving "whoever acted last" from the shared event log — combat
  // actions and other non-exploration events share that log and would
  // otherwise desync the handoff). The queue is deterministic: the very
  // first resolution hands off to the second party member; every
  // resolution after that hands back to the first party member.
  const members = listPlayMembers(campaignId);
  const priorTurnNumber = campaign.turn_number ?? 0;
  const nextIndex = priorTurnNumber < 2 ? 1 : 0;
  const nextActor = members[nextIndex]?.username ?? campaign.owner;

  const turnNumber = priorTurnNumber + 1;

  updatePlayCampaign({
    ...campaign,
    current_actor: nextActor,
    turn_number: turnNumber,
  });

  return Response.json(
    {
      sequence: event.sequence,
      kind: event.kind,
      actor: event.actor,
      text: event.text,
      next_actor: nextActor,
      turn_number: turnNumber,
    },
    { status: 201 },
  );
}
