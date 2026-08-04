import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requirePlayCampaign } from "../../../http.js";
import { createPlayEvent, getNextPlayEventSequence, updatePlayCampaign } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const currentActor = campaign.current_actor ?? null;

  // Only the player currently up in the queue may post an action; the owner
  // never acts through this endpoint (they narrate/resolve instead).
  if (username === campaign.owner || currentActor === null || username !== currentActor) {
    return Response.json({ error: "it is not your turn to act" }, { status: 409 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { type, text } = (body ?? {}) as { type?: unknown; text?: unknown };

  const validType = requireNonEmptyString(type, "type");
  if (validType instanceof Response) return validType;

  const validText = requireNonEmptyString(text, "text");
  if (validText instanceof Response) return validText;

  const sequence = getNextPlayEventSequence(campaignId);
  const event = createPlayEvent(campaignId, {
    sequence,
    kind: "action",
    actor: username,
    type: validType,
    text: validText,
  });

  updatePlayCampaign({
    ...campaign,
    current_actor: campaign.owner,
  });

  return Response.json(
    {
      sequence: event.sequence,
      kind: event.kind,
      actor: event.actor,
      type: event.type,
      text: event.text,
      next_actor: "dm",
    },
    { status: 201 },
  );
}
