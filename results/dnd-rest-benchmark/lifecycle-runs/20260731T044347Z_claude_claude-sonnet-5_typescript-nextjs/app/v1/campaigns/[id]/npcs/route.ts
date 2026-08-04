import {
  CampaignNpc,
  createCampaignNpc,
  hasCampaignFaction,
  hasCampaignNpc,
} from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name, faction_id, disposition } = (body ?? {}) as {
    id?: unknown;
    name?: unknown;
    faction_id?: unknown;
    disposition?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  if (faction_id !== null && faction_id !== undefined && typeof faction_id !== "string") {
    return Response.json({ error: "faction_id must be a string or null" }, { status: 400 });
  }

  if (typeof disposition !== "number" || !Number.isFinite(disposition)) {
    return Response.json({ error: "disposition must be a number" }, { status: 400 });
  }

  const normalizedFactionId = typeof faction_id === "string" ? faction_id : null;

  if (normalizedFactionId !== null && !hasCampaignFaction(campaignId, normalizedFactionId)) {
    return Response.json(
      { error: `faction ${normalizedFactionId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  if (hasCampaignNpc(campaignId, validId)) {
    return Response.json(
      { error: `npc ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const npc: CampaignNpc = {
    id: validId,
    name: validName,
    faction_id: normalizedFactionId,
    disposition,
  };
  createCampaignNpc(campaignId, npc);

  return Response.json(npc, { status: 201 });
}
