import { requireSession } from "../../../../auth/session.js";
import { parseJsonBody, requireNonEmptyString } from "../../../../http.js";
import { requireCampaignOwner, requirePlayCampaign } from "../../../http.js";
import {
  createPlayRelationship,
  getPlayMemberForUser,
  hasPlayMemberCharacter,
  hasPlayNpc,
  hasPlayRelationship,
  listPlayRelationships,
  MAX_RELATIONSHIP_SCORE,
  MIN_RELATIONSHIP_SCORE,
  PlayRelationship,
} from "../../../store.js";

function isCampaignEntity(campaignId: string, entityId: string): boolean {
  return hasPlayMemberCharacter(campaignId, entityId) || hasPlayNpc(campaignId, entityId);
}

function serializeRelationship(relationship: PlayRelationship) {
  return {
    source_id: relationship.source_id,
    target_id: relationship.target_id,
    kind: relationship.kind,
    score: relationship.score,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const ownerCheck = requireCampaignOwner(
    campaign,
    session.user.username,
    "only the campaign dm may create relationship edges",
  );
  if (ownerCheck) return ownerCheck;

  const parsed = await parseJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body as {
    source_id?: unknown;
    target_id?: unknown;
    kind?: unknown;
    score?: unknown;
  };

  const validSourceId = requireNonEmptyString(body.source_id, "source_id");
  if (validSourceId instanceof Response) return validSourceId;

  const validTargetId = requireNonEmptyString(body.target_id, "target_id");
  if (validTargetId instanceof Response) return validTargetId;

  const validKind = requireNonEmptyString(body.kind, "kind");
  if (validKind instanceof Response) return validKind;

  if (validSourceId === validTargetId) {
    return Response.json({ error: "source_id and target_id must differ" }, { status: 400 });
  }

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

  if (!isCampaignEntity(campaignId, validSourceId)) {
    return Response.json(
      { error: `campaign entity ${validSourceId} not found` },
      { status: 404 },
    );
  }

  if (!isCampaignEntity(campaignId, validTargetId)) {
    return Response.json(
      { error: `campaign entity ${validTargetId} not found` },
      { status: 404 },
    );
  }

  if (hasPlayRelationship(campaignId, validSourceId, validTargetId, validKind)) {
    return Response.json(
      {
        error: `relationship ${validSourceId} -> ${validTargetId} (${validKind}) already exists in campaign ${campaignId}`,
      },
      { status: 409 },
    );
  }

  const relationship = createPlayRelationship(campaignId, {
    source_id: validSourceId,
    target_id: validTargetId,
    kind: validKind,
    score,
  });

  return Response.json(serializeRelationship(relationship), { status: 201 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: campaignId } = await params;

  const session = requireSession(request);
  if (!session.ok) return session.response;

  const campaign = requirePlayCampaign(campaignId);
  if (campaign instanceof Response) return campaign;

  const username = session.user.username;
  const isDm = username === campaign.owner;
  const isMember = isDm || getPlayMemberForUser(campaignId, username) !== undefined;
  if (!isMember) {
    return Response.json(
      { error: `${username} is not a member of campaign ${campaignId}` },
      { status: 403 },
    );
  }

  const edges = listPlayRelationships(campaignId).map(serializeRelationship);
  return Response.json({ edges }, { status: 200 });
}
