import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { badRequest, forbidden, notFound } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignFeedEvents,
  getPlayCampaignMember,
} from "../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

function parseIntParameter(
  value: string | null,
  min: number,
  max: number | null
): number | null {
  if (value === null) return null;
  const n = Number(value);
  if (!Number.isInteger(n)) return null;
  if (n < min) return null;
  if (max !== null && n > max) return null;
  return n;
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

  const isMember =
    campaign.owner === auth.user.username ||
    getPlayCampaignMember(id, auth.user.username) !== null;
  if (!isMember) {
    return forbidden();
  }

  const { searchParams } = new URL(req.url);
  const rawCursor = searchParams.get("cursor");
  const rawLimit = searchParams.get("limit");

  const cursor = rawCursor === null ? 0 : parseIntParameter(rawCursor, 0, null);
  const limit = rawLimit === null ? 2 : parseIntParameter(rawLimit, 1, 3);

  if (cursor === null || limit === null) {
    return badRequest();
  }

  const result = getPlayCampaignFeedEvents(id, cursor, limit);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
