import {
  CampaignEquipmentAssignment,
  createCampaignEquipmentAssignment,
  hasCampaignCharacter,
} from "../../../../store.js";
import { requireCampaign } from "../../../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../../http.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; character_id: string }> },
) {
  const { id: campaignId, character_id: characterId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  if (!hasCampaignCharacter(campaignId, characterId)) {
    return Response.json(
      { error: `character ${characterId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { item_slug, quantity } = (body ?? {}) as {
    item_slug?: unknown;
    quantity?: unknown;
  };

  const validItemSlug = requireNonEmptyString(item_slug, "item_slug");
  if (validItemSlug instanceof Response) return validItemSlug;

  if (typeof quantity !== "number" || !Number.isInteger(quantity) || quantity < 1) {
    return Response.json({ error: "quantity must be a positive integer" }, { status: 400 });
  }

  const assignment: CampaignEquipmentAssignment = {
    character_id: characterId,
    item_slug: validItemSlug,
    quantity,
  };
  createCampaignEquipmentAssignment(campaignId, assignment);

  return Response.json(assignment, { status: 200 });
}
