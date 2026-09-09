import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../../../lib/http.js";
import {
  getPlayCampaign,
  restoreCampaignBackup,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; backup_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, backup_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const backup = restoreCampaignBackup(id, backup_id);
  if (!backup) {
    return notFound();
  }

  return NextResponse.json(backup);
}
