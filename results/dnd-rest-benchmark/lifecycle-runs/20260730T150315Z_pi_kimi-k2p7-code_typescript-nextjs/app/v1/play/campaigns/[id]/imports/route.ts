import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  createPlayCampaignImport,
  getPlayCampaign,
} from "../../../../../lib/storage.js";

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

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const parsed = await parseJsonBody(req);
  if (!parsed.ok) return parsed.response;

  const b = parsed.body;
  const keys = Object.keys(b);
  if (
    keys.length !== 3 ||
    !("version" in b) ||
    !("story" in b) ||
    !("status" in b)
  ) {
    return badRequest();
  }

  if (
    b.version !== 1 ||
    typeof b.story !== "string" ||
    b.story.length === 0 ||
    (b.status !== "lobby" && b.status !== "started")
  ) {
    return badRequest();
  }

  const snapshot = { version: 1 as const, story: b.story, status: b.status };
  const result = createPlayCampaignImport(id, snapshot);
  if (!result) {
    return badRequest();
  }

  return NextResponse.json(result);
}
