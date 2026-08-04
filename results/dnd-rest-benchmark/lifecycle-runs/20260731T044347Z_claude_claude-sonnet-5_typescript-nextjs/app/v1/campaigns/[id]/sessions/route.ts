import { CampaignSession, createCampaignSession, hasCampaignSession } from "../../store.js";
import { requireCampaign } from "../../http.js";
import { parseJsonBody, requireNonEmptyString } from "../../../http.js";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { id, starts_at, duration_minutes, agenda } = (body ?? {}) as {
    id?: unknown;
    starts_at?: unknown;
    duration_minutes?: unknown;
    agenda?: unknown;
  };

  const validId = requireNonEmptyString(id, "id");
  if (validId instanceof Response) return validId;

  const validStartsAt = requireNonEmptyString(starts_at, "starts_at");
  if (validStartsAt instanceof Response) return validStartsAt;

  if (
    typeof duration_minutes !== "number" ||
    !Number.isFinite(duration_minutes) ||
    duration_minutes <= 0
  ) {
    return Response.json(
      { error: "duration_minutes must be a positive number" },
      { status: 400 },
    );
  }

  if (!Array.isArray(agenda) || agenda.some((a) => typeof a !== "string" || a.length === 0)) {
    return Response.json(
      { error: "agenda must be an array of non-empty strings" },
      { status: 400 },
    );
  }

  if (hasCampaignSession(campaignId, validId)) {
    return Response.json(
      { error: `session ${validId} already exists in campaign ${campaignId}` },
      { status: 409 },
    );
  }

  const session: CampaignSession = {
    id: validId,
    starts_at: validStartsAt,
    duration_minutes,
    agenda: agenda as string[],
    present: [],
    absent: [],
  };
  createCampaignSession(campaignId, session);

  return Response.json(
    {
      id: session.id,
      starts_at: session.starts_at,
      duration_minutes: session.duration_minutes,
      agenda_count: session.agenda.length,
    },
    { status: 201 },
  );
}
