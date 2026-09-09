import { NextResponse } from "next/server";
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
  createPlayCampaignSafeTurn,
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignSafeTurns,
} from "../../../../../lib/storage.js";
import {
  isNonEmptyString,
  isPositiveInteger,
} from "../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function POST(
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
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  if (
    !isNonEmptyString(b.submission_id) ||
    !isNonEmptyString(b.action) ||
    !isPositiveInteger(b.expected_turn)
  ) {
    return badRequest();
  }

  const result = createPlayCampaignSafeTurn(
    id,
    b.submission_id,
    b.action,
    b.expected_turn
  );

  if (result === null) {
    return notFound();
  }

  if (result === "conflict") {
    return conflict();
  }

  if ("current_turn" in result) {
    return NextResponse.json(
      { current_turn: result.current_turn },
      { status: 409 }
    );
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
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const state = getPlayCampaignSafeTurns(id);
  if (!state) {
    return notFound();
  }

  return ok(state);
}
