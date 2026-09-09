import { NextResponse } from "next/server";
import { readPlayCampaignDowntimeAllocation } from "../../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const actor = authorization.slice(prefix.length);
  return actor.length > 0 ? actor : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string; activity_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id, activity_id } = await params;
  const result = readPlayCampaignDowntimeAllocation(id, char_id, activity_id, actor);
  if (result.result === "found") return NextResponse.json(result.allocation);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Character, activity, or allocation not found" }, { status: 404 });
}
