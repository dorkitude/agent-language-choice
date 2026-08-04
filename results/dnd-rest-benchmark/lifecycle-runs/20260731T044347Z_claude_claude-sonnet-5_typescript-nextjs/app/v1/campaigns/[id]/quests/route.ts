import { CampaignQuest, createCampaignQuest, hasCampaignQuest } from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

const VALID_STATUSES = ["active", "completed", "blocked"];

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, title, status, milestones } = (body ?? {}) as {
    id?: unknown;
    title?: unknown;
    status?: unknown;
    milestones?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validTitle = requireNonEmptyString(title, "title");
  if (validTitle instanceof Response) return validTitle;

  if (typeof status !== "string" || !VALID_STATUSES.includes(status)) {
    return Response.json(
      { error: `status must be one of: ${VALID_STATUSES.join(", ")}` },
      { status: 400 },
    );
  }

  if (
    !Array.isArray(milestones) ||
    milestones.some((m) => typeof m !== "string" || m.length === 0)
  ) {
    return Response.json(
      { error: "milestones must be an array of non-empty strings" },
      { status: 400 },
    );
  }

  if (hasCampaignQuest(campaignId, validId)) {
    return Response.json(
      { error: `quest ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const quest: CampaignQuest = {
    id: validId,
    title: validTitle,
    status: status as CampaignQuest["status"],
    milestones: milestones as string[],
    completedMilestones: [],
  };
  createCampaignQuest(campaignId, quest);

  return Response.json(
    {
      id: quest.id,
      title: quest.title,
      status: quest.status,
      milestones_total: quest.milestones.length,
      milestones_done: quest.completedMilestones.length,
    },
    { status: 201 },
  );
}
