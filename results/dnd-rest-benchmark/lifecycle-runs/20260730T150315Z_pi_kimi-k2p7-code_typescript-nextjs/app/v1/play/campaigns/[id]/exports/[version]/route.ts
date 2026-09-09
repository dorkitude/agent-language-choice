import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignExportByVersion,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; version: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, version: versionParam } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const version = Number(versionParam);
  if (Number.isNaN(version)) {
    return notFound();
  }

  const result = getPlayCampaignExportByVersion(id, version);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
