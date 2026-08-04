import { CampaignEvent, createCampaignEvent, hasCampaignEvent } from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, kind, summary } = (body ?? {}) as {
    id?: unknown;
    kind?: unknown;
    summary?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validKind = requireNonEmptyString(kind, "kind");
  if (validKind instanceof Response) return validKind;

  const validSummary = requireNonEmptyString(summary, "summary");
  if (validSummary instanceof Response) return validSummary;

  if (hasCampaignEvent(campaignId, validId)) {
    return Response.json(
      { error: `event ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const event: CampaignEvent = { id: validId, kind: validKind, summary: validSummary };
  createCampaignEvent(campaignId, event);

  return Response.json({ id: event.id, kind: event.kind }, { status: 201 });
}
