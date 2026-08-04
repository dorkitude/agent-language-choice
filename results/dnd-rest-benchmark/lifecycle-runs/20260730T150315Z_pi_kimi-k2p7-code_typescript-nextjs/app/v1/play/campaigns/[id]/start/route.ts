import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../lib/auth.js";
import { conflict, forbidden, notFound } from "../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  startPlayCampaign,
} from "../../../../../lib/storage.js";

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

  const members = getPlayCampaignMembers(id);
  if (members.length < 2) {
    return conflict();
  }

  const result = startPlayCampaign(id, members[0].username);
  if (!result) {
    return conflict();
  }

  return NextResponse.json(result);
}
