import { NextResponse } from "next/server";
import { readPlayCampaignReplay } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!value?.startsWith(prefix) || value.length === prefix.length) return undefined;
  const username = value.slice(prefix.length);
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || userRole(username)
    ? username
    : undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignReplay((await params).id, who);
  if (result.result === "found") return NextResponse.json(result.replay);
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
