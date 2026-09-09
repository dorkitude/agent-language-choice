import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import {
  badRequest,
  forbidden,
  notFound,
  parseJsonBody,
} from "../../../../../../lib/http.js";
import {
  advancePlayCampaignCalendar,
  getPlayCampaign,
} from "../../../../../../lib/storage.js";
import { isInteger } from "../../../../../../lib/validate.js";

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
    !isInteger(b.days) ||
    (b.days as number) < 1 ||
    (b.days as number) > 30
  ) {
    return badRequest();
  }

  const result = advancePlayCampaignCalendar(id, b.days as number);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
