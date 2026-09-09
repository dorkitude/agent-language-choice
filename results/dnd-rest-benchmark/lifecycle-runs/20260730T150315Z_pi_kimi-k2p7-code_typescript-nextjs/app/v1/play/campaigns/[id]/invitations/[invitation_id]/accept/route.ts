import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../../lib/auth.js";
import {
  conflict,
  forbidden,
  notFound,
} from "../../../../../../../lib/http.js";
import {
  acceptPlayCampaignInvitation,
  getPlayCampaign,
} from "../../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; invitation_id: string }> }
) {
  const { id, invitation_id } = await params;

  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const result = acceptPlayCampaignInvitation(
    id,
    invitation_id,
    auth.user.username
  );

  if (result === "not_found") {
    return notFound();
  }
  if (result === "forbidden") {
    return forbidden();
  }
  if (result === "conflict") {
    return conflict();
  }

  return NextResponse.json(result);
}
