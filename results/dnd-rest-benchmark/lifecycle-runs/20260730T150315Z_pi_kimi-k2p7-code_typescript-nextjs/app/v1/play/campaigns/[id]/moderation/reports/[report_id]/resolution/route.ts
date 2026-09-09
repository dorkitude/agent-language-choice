import { requireBearerAuth } from "../../../../../../../../lib/auth.js";
import {
  badRequest,
  conflict,
  forbidden,
  notFound,
  ok,
  parseJsonBody,
} from "../../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  resolvePlayCampaignModerationReport,
} from "../../../../../../../../lib/storage.js";
import type { ResolvePlayCampaignModerationReportInput } from "../../../../../../../../lib/storage.js";
import { isNonEmptyString } from "../../../../../../../../lib/validate.js";

export const dynamic = "force-dynamic";

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ id: string; report_id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) return auth.response;

  const { id, report_id } = await params;

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
  if (b.action !== "allow" && b.action !== "remove") {
    return badRequest();
  }
  if (!isNonEmptyString(b.note)) {
    return badRequest();
  }

  const input: ResolvePlayCampaignModerationReportInput = {
    action: b.action,
    note: b.note,
  };

  const result = resolvePlayCampaignModerationReport(
    id,
    report_id,
    auth.user.username,
    input
  );
  if (result === null) {
    return notFound();
  }
  if (result === "not_found") {
    return notFound();
  }
  if (result === "conflict") {
    return conflict();
  }

  return ok(result);
}
