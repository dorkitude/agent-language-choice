import { getCampaignQuest, updateCampaignQuest } from "../../../../store.js";
import { requireCampaign } from "../../../../http.js";
import { parseJsonBody } from "../../../../../http.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; quest_id: string }> },
) {
  const { id: campaignId, quest_id: questId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const quest = getCampaignQuest(campaignId, questId);
  if (!quest) {
    return Response.json(
      { error: `quest ${questId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { completed } = (body ?? {}) as { completed?: unknown };

  if (
    !Array.isArray(completed) ||
    completed.some((m) => typeof m !== "string" || m.length === 0)
  ) {
    return Response.json(
      { error: "completed must be an array of non-empty strings" },
      { status: 400 },
    );
  }

  const invalid = completed.filter((m) => !quest.milestones.includes(m));
  if (invalid.length > 0) {
    return Response.json(
      { error: `unknown milestones: ${invalid.join(", ")}` },
      { status: 400 },
    );
  }

  const completedMilestones = Array.from(
    new Set([...quest.completedMilestones, ...(completed as string[])]),
  );

  const updated = {
    ...quest,
    completedMilestones,
    status:
      quest.status === "active" && completedMilestones.length === quest.milestones.length
        ? ("completed" as const)
        : quest.status,
  };
  updateCampaignQuest(campaignId, updated);

  return Response.json({
    id: updated.id,
    status: updated.status,
    milestones_total: updated.milestones.length,
    milestones_done: updated.completedMilestones.length,
  });
}
