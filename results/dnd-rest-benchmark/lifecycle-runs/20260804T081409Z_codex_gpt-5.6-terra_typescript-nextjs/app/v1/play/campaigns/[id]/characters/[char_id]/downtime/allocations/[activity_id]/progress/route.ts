import { NextResponse } from "next/server";
import { progressPlayCampaignDowntimeAllocation } from "../../../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const actor = authorization.slice(prefix.length);
  return actor.length > 0 ? actor : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string; activity_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "player") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const { id, char_id, activity_id } = await params;
  const result = progressPlayCampaignDowntimeAllocation(id, char_id, activity_id, actor);
  if (result.result === "progressed") return NextResponse.json(result.allocation);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Character, activity, or allocation not found" }, { status: 404 });
}
