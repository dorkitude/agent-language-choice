import {
  CampaignCraftingProject,
  createCampaignCraftingProject,
  hasCampaignCraftingProject,
} from "../../../store.js";
import { requireCampaign } from "../../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, character_id, item_slug, days_required, cost_gp } = (body ?? {}) as {
    id?: unknown;
    character_id?: unknown;
    item_slug?: unknown;
    days_required?: unknown;
    cost_gp?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validCharacterId = requireNonEmptyString(character_id, "character_id");
  if (validCharacterId instanceof Response) return validCharacterId;

  const validItemSlug = requireNonEmptyString(item_slug, "item_slug");
  if (validItemSlug instanceof Response) return validItemSlug;

  if (
    typeof days_required !== "number" ||
    !Number.isInteger(days_required) ||
    days_required < 1
  ) {
    return Response.json(
      { error: "days_required must be a positive integer" },
      { status: 400 },
    );
  }

  if (typeof cost_gp !== "number" || !Number.isFinite(cost_gp) || cost_gp < 0) {
    return Response.json({ error: "cost_gp must be a non-negative number" }, { status: 400 });
  }

  if (hasCampaignCraftingProject(campaignId, validId)) {
    return Response.json(
      { error: `crafting project ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const project: CampaignCraftingProject = {
    id: validId,
    character_id: validCharacterId,
    item_slug: validItemSlug,
    days_required,
    days_completed: 0,
    cost_gp,
    status: "active",
  };
  createCampaignCraftingProject(campaignId, project);

  return Response.json(
    {
      id: project.id,
      character_id: project.character_id,
      item_slug: project.item_slug,
      days_required: project.days_required,
      days_completed: project.days_completed,
      status: project.status,
    },
    { status: 201 },
  );
}
