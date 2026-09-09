import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  created,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../lib/http.js";
import {
  createPlayCampaignModerationReport,
  getPlayCampaign,
  getPlayCampaignMember,
  getPlayCampaignModerationReports,
} from "../../../../../../lib/storage.js";
import type { CreatePlayCampaignModerationReportInput } from "../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../lib/validate.js";

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
    !isNonEmptyString(b.report_id) ||
    !isNonEmptyString(b.target_id) ||
    !isNonEmptyString(b.reason)
  ) {
    return badRequest();
  }

  const input: CreatePlayCampaignModerationReportInput = {
    report_id: b.report_id,
    target_id: b.target_id,
    reason: b.reason,
  };

  const result = createPlayCampaignModerationReport(id, auth.user.username, input);
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

  const isOwner = campaign.owner === auth.user.username;
  if (!isOwner && !getPlayCampaignMember(id, auth.user.username)) {
    return forbidden();
  }

  const result = getPlayCampaignModerationReports(id);
  if (result === null) {
    return notFound();
  }

  return ok(result);
}
