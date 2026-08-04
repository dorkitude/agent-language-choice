import { getCampaignCraftingProject, updateCampaignCraftingProject } from "../../../../../store.js";
import { requireCampaign } from "../../../../../http.js";
import { parseJsonBody } from "../../../../../../http.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; project_id: string }> },
) {
  const { id: campaignId, project_id: projectId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const project = getCampaignCraftingProject(campaignId, projectId);
  if (!project) {
    return Response.json(
      { error: `crafting project ${projectId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { days } = (body ?? {}) as { days?: unknown };

  if (typeof days !== "number" || !Number.isInteger(days) || days < 1) {
    return Response.json({ error: "days must be a positive integer" }, { status: 400 });
  }

  if (project.status === "complete") {
    return Response.json(
      { error: `crafting project ${projectId} is already complete` },
      { status: 409 },
    );
  }

  const daysCompleted = Math.min(project.days_completed + days, project.days_required);
  const status = daysCompleted >= project.days_required ? "complete" : "active";

  const updated = {
    ...project,
    days_completed: daysCompleted,
    status: status as "active" | "complete",
  };
  updateCampaignCraftingProject(campaignId, updated);

  return Response.json({
    id: updated.id,
    days_completed: updated.days_completed,
    status: updated.status,
  });
}
