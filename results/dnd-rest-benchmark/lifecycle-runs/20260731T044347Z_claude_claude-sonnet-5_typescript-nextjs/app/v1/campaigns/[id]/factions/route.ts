import { CampaignFaction, createCampaignFaction, hasCampaignFaction } from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

const VALID_STANCES = ["friendly", "neutral", "hostile"];

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, name, stance } = (body ?? {}) as {
    id?: unknown;
    name?: unknown;
    stance?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validName = requireNonEmptyString(name, "name");
  if (validName instanceof Response) return validName;

  if (typeof stance !== "string" || !VALID_STANCES.includes(stance)) {
    return Response.json(
      { error: `stance must be one of: ${VALID_STANCES.join(", ")}` },
      { status: 400 },
    );
  }

  if (hasCampaignFaction(campaignId, validId)) {
    return Response.json(
      { error: `faction ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const faction: CampaignFaction = {
    id: validId,
    name: validName,
    stance: stance as CampaignFaction["stance"],
  };
  createCampaignFaction(campaignId, faction);

  return Response.json(faction, { status: 201 });
}
