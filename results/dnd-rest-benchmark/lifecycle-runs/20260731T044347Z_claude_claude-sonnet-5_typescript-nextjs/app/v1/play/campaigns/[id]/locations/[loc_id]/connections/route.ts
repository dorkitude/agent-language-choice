import { requireSession } from "../../../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../http.js";
import {
  createPlayLocationConnection,
  hasPlayLocation,
  hasPlayLocationConnection,
  PlayLocationConnection,
} from "../../../../../store.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; loc_id: string }> },
) {
  const { id: campaignId, loc_id: fromId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may create a connection",
  );
  if (ownerCheck) return ownerCheck;

  if (!hasPlayLocation(campaignId, fromId)) {
    return Response.json({ error: `location ${fromId} not found` }, { status: 404 });
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { to_id, travel_turns } = (body ?? {}) as { to_id?: unknown; travel_turns?: unknown };

  const validToId = requireNonEmptyString(to_id, "to_id");
  if (validToId instanceof Response) return validToId;

  if (typeof travel_turns !== "number" || !Number.isInteger(travel_turns) || travel_turns < 1) {
    return Response.json({ error: "travel_turns must be a positive integer" }, { status: 400 });
  }

  if (!hasPlayLocation(campaignId, validToId)) {
    return Response.json({ error: `location ${validToId} not found` }, { status: 400 });
  }

  if (hasPlayLocationConnection(campaignId, fromId, validToId)) {
    return Response.json(
      { error: `connection from ${fromId} to ${validToId} already exists` },
      { status: 400 },
    );
  }

  const connection: PlayLocationConnection = {
    campaign_id: campaignId,
    from_id: fromId,
    to_id: validToId,
    travel_turns,
  };
  createPlayLocationConnection(connection);

  return Response.json(
    { from_id: fromId, to_id: validToId, travel_turns },
    { status: 201 },
  );
}
