import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  internalServerError,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignSpectator,
  getPlayCampaign,
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

  const spectatorId = parsed.body.spectator_id;
  if (typeof spectatorId !== "string" || spectatorId.length === 0) {
    return badRequest();
  }

  const result = createPlayCampaignSpectator(id, spectatorId);
  if (result === null) {
    return internalServerError("Failed to create spectator");
  }
  if (result === "conflict") {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}
