import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import {
  badRequest,
  notFound,
  parseJsonBody,
} from "../../../../../lib/http.js";
import { getPlayCampaign } from "../../../../../lib/storage.js";
import {
  getMaintenanceMode,
  setMaintenanceMode,
} from "../../../../../lib/maintenance.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const auth = requireBearerAuth(req, "dm");
  if (!auth.ok) {
    return auth.response;
  }

  const { id } = await params;
  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const maintenance = parsed.body.maintenance;
  if (typeof maintenance !== "boolean") {
    return badRequest();
  }

  setMaintenanceMode(maintenance);
  return NextResponse.json({ maintenance: getMaintenanceMode() });
}
