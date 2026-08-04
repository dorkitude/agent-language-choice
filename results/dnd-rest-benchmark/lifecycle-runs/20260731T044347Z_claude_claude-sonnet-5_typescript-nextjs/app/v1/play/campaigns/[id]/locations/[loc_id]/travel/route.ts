import { requireSession } from "../../../../../../auth/session.js";
import { requirePlayCampaign } from "../../../../../http.js";
import {
  getPlayLocation,
  hasPlayMemberForUser,
  listPlayLocationConnections,
  PlayLocationConnection,
} from "../../../../../store.js";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; loc_id: string }> },
) {
  const { id: campaignId, loc_id: fromId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isMember = username === campaign.owner || hasPlayMemberForUser(campaignId, username);
  if (!isMember) {
    return Response.json({ error: `${username} is not a member of campaign ${campaignId}` }, { status: 403 });
  }

  const connections = listPlayLocationConnections(campaignId, fromId);
  const destinations = connections
    .map((connection: PlayLocationConnection) => {
      const location = getPlayLocation(campaignId, connection.to_id);
      if (!location) return null;
      return { id: location.id, name: location.name, travel_turns: connection.travel_turns };
    })
    .filter((destination): destination is { id: string; name: string; travel_turns: number } => destination !== null);

  return Response.json({ destinations }, { status: 200 });
}
