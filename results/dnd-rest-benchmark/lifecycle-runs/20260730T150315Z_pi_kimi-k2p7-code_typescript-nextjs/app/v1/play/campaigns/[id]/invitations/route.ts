import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  created,
  ok,
  parseJsonBody,
} from "../../../../../lib/http.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";
import {
  createPlayCampaignInvitation,
  getPlayCampaign,
  getPlayCampaignInvitations,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

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
    !isNonEmptyString(b.invitation_id) ||
    !isNonEmptyString(b.username) ||
    !isNonEmptyString(b.character_id)
  ) {
    return badRequest();
  }

  const result = createPlayCampaignInvitation(id, {
    invitation_id: b.invitation_id,
    username: b.username,
    character_id: b.character_id,
  });

  if (result === "not_found") {
    return notFound();
  }
  if (result === "bad_request") {
    return badRequest();
  }
  if (result === "conflict") {
    return conflict();
  }

  return NextResponse.json(result, { status: 201 });
}

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const invitations = getPlayCampaignInvitations(id);

  if (campaign.owner === auth.user.username) {
    return ok({ invitations });
  }

  const filtered = invitations.filter(
    (inv) => inv.username === auth.user.username
  );

  return ok({ invitations: filtered });
}
