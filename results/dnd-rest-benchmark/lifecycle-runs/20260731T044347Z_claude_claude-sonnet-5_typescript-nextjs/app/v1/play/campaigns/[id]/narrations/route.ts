import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { createPlayEvent, getNextPlayEventSequence, hasActiveDelegatedPower } from "../../../store.js";
import { requirePlayCampaign } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isOwner = username === campaign.owner;
  const canNarrate = isOwner || hasActiveDelegatedPower(campaignId, username, "narrate");
  if (!canNarrate) {
    return Response.json(
      { error: "only the owning dm may narrate this campaign" },
      { status: 403 },
    );
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
    kind: "narration",
    actor: username,
    text: validText,
  });

  return Response.json(event, { status: 201 });
}
