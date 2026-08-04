import { requireSession } from "../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";
import { requirePlayCampaign } from "../../../../http.js";
import {
  createPlayEvent,
  getFirstPlayLocation,
  getNextPlayEventSequence,
  listPlayLocationConnections,
  updatePlayCampaign,
} from "../../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const currentActor = campaign.current_actor ?? null;

  // Only the player currently up in the queue may travel; the owner never
  // acts through this endpoint. Mirrors the check in POST /actions.
  if (username === campaign.owner || currentActor === null || username !== currentActor) {
    return Response.json({ error: "it is not your turn to act" }, { status: 409 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { destination_id } = (body ?? {}) as { destination_id?: unknown };

  const validDestinationId = requireNonEmptyString(destination_id, "destination_id");
  if (validDestinationId instanceof Response) return validDestinationId;

  const fromLocationId = campaign.current_location_id ?? getFirstPlayLocation(campaignId)?.id;
  if (!fromLocationId) {
    return Response.json({ error: `no valid route to ${validDestinationId}` }, { status: 409 });
  }

  const connections = listPlayLocationConnections(campaignId, fromLocationId);
  const connection = connections.find((item) => item.to_id === validDestinationId);
  if (!connection) {
    return Response.json({ error: `no valid route to ${validDestinationId}` }, { status: 409 });
  }

  const sequence = getNextPlayEventSequence(campaignId);
  const event = createPlayEvent(campaignId, {
    sequence,
    kind: "travel",
    actor: username,
    text: `Traveled to ${validDestinationId}`,
  });

  updatePlayCampaign({
    ...campaign,
    current_actor: campaign.owner,
    current_location_id: validDestinationId,
  });

  return Response.json(
    {
      sequence: event.sequence,
      kind: event.kind,
      actor: event.actor,
      destination_id: validDestinationId,
      travel_turns: connection.travel_turns,
      next_actor: "dm",
    },
    { status: 201 },
  );
}
