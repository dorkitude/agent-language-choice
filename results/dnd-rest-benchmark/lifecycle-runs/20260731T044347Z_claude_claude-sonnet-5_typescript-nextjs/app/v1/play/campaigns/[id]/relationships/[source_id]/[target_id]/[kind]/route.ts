import { requireSession } from "../../../../../../../auth/session.js";
import { parseJsonBody } from "../../../../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../../../../http.js";
import {
  getPlayRelationship,
  MAX_RELATIONSHIP_SCORE,
  MIN_RELATIONSHIP_SCORE,
  updatePlayRelationship,
} from "../../../../../../store.js";

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; source_id: string; target_id: string; kind: string }> },
) {
  const { id: campaignId, source_id: sourceId, target_id: targetId, kind } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may update relationship edges",
  );
  if (ownerCheck) return ownerCheck;

  const relationship = getPlayRelationship(campaignId, sourceId, targetId, kind);
  if (!relationship) {
    return Response.json(
      { error: `relationship ${sourceId} -> ${targetId} (${kind}) not found` },
      { status: 404 },
    );
  }

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as { score?: unknown };

  const { score } = body;
  if (
    typeof score !== "number" ||
    !Number.isInteger(score) ||
    score < MIN_RELATIONSHIP_SCORE ||
    score > MAX_RELATIONSHIP_SCORE
  ) {
    return Response.json(
      { error: `score must be an integer between ${MIN_RELATIONSHIP_SCORE} and ${MAX_RELATIONSHIP_SCORE}` },
      { status: 400 },
    );
  }

  const updated = updatePlayRelationship(campaignId, { ...relationship, score });

  return Response.json(
    {
      source_id: updated.source_id,
      target_id: updated.target_id,
      kind: updated.kind,
      score: updated.score,
    },
    { status: 200 },
  );
}
