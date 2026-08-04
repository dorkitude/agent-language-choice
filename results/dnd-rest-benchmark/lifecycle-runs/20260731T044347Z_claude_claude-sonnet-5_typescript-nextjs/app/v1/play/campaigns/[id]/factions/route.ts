import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import { createPlayFaction, hasPlayFaction } from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create factions",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { faction_id?: unknown; name?: unknown };

  const validFactionId = requireNonEmptyString(body.faction_id, "faction_id");
  if (validFactionId instanceof Response) return validFactionId;

  const validName = requireNonEmptyString(body.name, "name");
  if (validName instanceof Response) return validName;

  if (hasPlayFaction(campaignId, validFactionId)) {
    return Response.json(
      { error: `faction ${validFactionId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const faction = createPlayFaction({
    campaign_id: campaignId,
    faction_id: validFactionId,
    name: validName,
  });

  return Response.json(
    { faction_id: faction.faction_id, name: faction.name },
    { status: 201 },
  );
}
