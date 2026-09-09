import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../../lib/http.js";
import { getPlayCampaign, revokeDelegation } from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ id: string; username: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, username } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  if (campaign.owner !== auth.user.username) {
    return forbidden();
  }

  const result = revokeDelegation(id, username);
  if (!result) {
    return notFound();
  }

  return NextResponse.json(result);
}
