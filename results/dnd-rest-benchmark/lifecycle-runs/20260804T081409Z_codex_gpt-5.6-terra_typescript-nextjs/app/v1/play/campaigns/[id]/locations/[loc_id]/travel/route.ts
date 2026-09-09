import { NextResponse } from "next/server";
import { readPlayCampaignTravel } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; loc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || roleForActor(actor) === undefined) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, loc_id } = await params;
  const result = readPlayCampaignTravel(id, actor, loc_id);
  if (result.result === "found") return NextResponse.json({ destinations: result.destinations });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or location not found" }, { status: 404 });
  return NextResponse.json({ error: "Forbidden" }, { status: 403 });
}
