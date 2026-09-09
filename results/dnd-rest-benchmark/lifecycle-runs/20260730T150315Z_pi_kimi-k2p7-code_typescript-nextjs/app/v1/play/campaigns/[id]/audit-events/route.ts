import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import {
  createPlayCampaignAuditEvent,
  getPlayCampaign,
  getPlayCampaignAuditEvents,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../lib/validate.js";

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
  if (!isNonEmptyString(b.kind) || !isNonEmptyString(b.correlation_id)) {
    return badRequest();
  }

  const role: "DM" | "player" = isOwner ? "DM" : "player";
  const result = createPlayCampaignAuditEvent(id, auth.user.username, role, {
    kind: b.kind,
    correlation_id: b.correlation_id,
  });

  if (result === null) {
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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const audit = getPlayCampaignAuditEvents(id);
  if (!audit) {
    return notFound();
  }

  return NextResponse.json(audit);
}
