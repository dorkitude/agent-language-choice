import { getCampaignSession, updateCampaignSession } from "../../../../store.js";
import { requireCampaign } from "../../../../http.js";
import { parseJsonBody } from "../../../../../http.js";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string; session_id: string }> },
) {
  const { id: campaignId, session_id: sessionId } = await params;

  const campaign = requireCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const session = getCampaignSession(campaignId, sessionId);
  if (!session) {
    return Response.json(
      { error: `session ${sessionId} not found in campaign ${campaignId}` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;

  const { present, absent } = (body ?? {}) as { present?: unknown; absent?: unknown };

  if (!Array.isArray(present) || present.some((p) => typeof p !== "string" || p.length === 0)) {
    return Response.json(
      { error: "present must be an array of non-empty strings" },
      { status: 400 },
    );
  }

  if (!Array.isArray(absent) || absent.some((a) => typeof a !== "string" || a.length === 0)) {
    return Response.json(
      { error: "absent must be an array of non-empty strings" },
      { status: 400 },
    );
  }

  const updated = {
    ...session,
    present: present as string[],
    absent: absent as string[],
  };
  updateCampaignSession(campaignId, updated);

  return Response.json({
    session_id: updated.id,
    present_count: updated.present.length,
    absent_count: updated.absent.length,
  });
}
