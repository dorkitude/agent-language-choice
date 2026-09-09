import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignRelationship,
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignRelationships,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    typeof b.source_id !== "string" ||
    b.source_id.length === 0 ||
    typeof b.target_id !== "string" ||
    b.target_id.length === 0 ||
    typeof b.kind !== "string" ||
    b.kind.length === 0
  ) {
    return badRequest();
  }

  if (typeof b.score !== "number" || !Number.isInteger(b.score)) {
    return badRequest();
  }
  const score = b.score;
  if (score < -100 || score > 100) {
    return badRequest();
  }

  if (b.source_id === b.target_id) {
    return badRequest();
  }

  const result = createPlayCampaignRelationship(
    id,
    b.source_id,
    b.target_id,
    b.kind,
    score
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return created(result);
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const isOwner = campaign.owner === auth.user.username;
  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);

  if (!isOwner && !isMember) {
    return forbidden();
  }

  const edges = getPlayCampaignRelationships(id);
  return ok({ edges });
}
