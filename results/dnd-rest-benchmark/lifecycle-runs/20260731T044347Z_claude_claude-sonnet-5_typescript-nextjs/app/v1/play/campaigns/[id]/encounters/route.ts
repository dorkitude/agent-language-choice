import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayEncounter,
  hasActivePlayEncounter,
  hasPlayEncounter,
  updatePlayCampaign,
} from "../../../store.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the owning dm may start an encounter",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { id?: unknown; name?: unknown };

  const id = requireNonEmptyString(body.id, "id");
  if (id instanceof Response) return id;

  const name = requireNonEmptyString(body.name, "name");
  if (name instanceof Response) return name;

  if (hasPlayEncounter(campaignId, id)) {
    return Response.json({ error: `encounter ${id} already exists` }, { status: 409 });
  }

  if (hasActivePlayEncounter(campaignId)) {
    return Response.json(
      { error: `play campaign ${campaignId} is already in combat` },
      { status: 409 },
    );
  }

  const encounter = createPlayEncounter({
    campaign_id: campaignId,
    id,
    name,
    status: "active",
    combatants: [],
  });

  if (campaign.phase !== "combat") {
    updatePlayCampaign({
      ...campaign,
      phase: "combat",
      pre_combat_actor: campaign.current_actor,
    });
  }

  return Response.json(
    {
      id: encounter.id,
      name: encounter.name,
      status: encounter.status,
      combatants: encounter.combatants,
    },
    { status: 201 },
  );
}
