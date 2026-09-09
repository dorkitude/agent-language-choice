import { NextResponse } from "next/server";
import { acceptPlayCampaignInvitation } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}
function known(value: string) { return value === "dm" || value === "player" || value === "player-a" || value === "player-b" || Boolean(userRole(value)); }

export async function POST(request: Request, { params }: { params: Promise<{ id: string; invitation_id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, invitation_id } = await params;
  const result = acceptPlayCampaignInvitation(id, invitation_id, who);
  if (result.result === "accepted") return NextResponse.json(result.invitation);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: result.result === "conflict" ? "Invitation already accepted" : "Invitation not found" }, { status: result.result === "conflict" ? 409 : 404 });
}
