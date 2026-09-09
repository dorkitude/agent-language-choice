import { NextResponse } from "next/server";
import { requireBearerAuth } from "../../../../../../lib/auth.js";
import { forbidden, notFound } from "../../../../../../lib/http.js";
import {
  getPlayCampaign,
  getPlayCampaignMembers,
  getPlayCampaignNpc,
} from "../../../../../../lib/storage.js";

export const dynamic = "force-dynamic";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string; npc_id: string }> }
) {
  const auth = requireBearerAuth(req);
  if (!auth.ok) return auth.response;

  const { id, npc_id } = await params;

  const campaign = getPlayCampaign(id);
  if (!campaign) {
    return notFound();
  }

  const members = getPlayCampaignMembers(id);
  const isMember = members.some((m) => m.username === auth.user.username);
  const isOwner = campaign.owner === auth.user.username;

  if (!isMember && !isOwner) {
    return forbidden();
  }

  const npc = getPlayCampaignNpc(id, npc_id);
  if (!npc) {
    return notFound();
  }

  if (isOwner) {
    return NextResponse.json({
      npc_id: npc.npc_id,
      name: npc.name,
      agenda: npc.agenda,
      public_status: npc.public_status,
    });
  }

  return NextResponse.json({
    npc_id: npc.npc_id,
    name: npc.name,
    public_status: npc.public_status,
  });
}
