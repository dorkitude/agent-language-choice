import { NextResponse } from "next/server";
import { readPlayCampaignDelegationAudit } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}
function known(username: string): boolean {
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || Boolean(userRole(username));
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignDelegationAudit((await params).id, who);
  if (result.result === "found") return NextResponse.json({ entries: result.entries });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
