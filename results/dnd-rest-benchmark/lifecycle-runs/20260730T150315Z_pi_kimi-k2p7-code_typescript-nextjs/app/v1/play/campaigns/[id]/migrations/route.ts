import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, created, forbidden, notFound, parseJsonBody } from "../../../../../lib/http.js";
import {
  createPlayCampaignMigration,
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
  if (
    !("schema_version" in b) ||
    !("story" in b)
  ) {
    return badRequest();
  }

  const result = createPlayCampaignMigration(id, {
    schema_version: b.schema_version,
    story: b.story,
  } as { schema_version: number; story: string });

  if (!result) {
    return notFound();
  }

  if (result === "bad_request") {
    return badRequest();
  }

  if (result.created) {
    return created(result.snapshot);
  }

  return NextResponse.json(result.snapshot);
}
