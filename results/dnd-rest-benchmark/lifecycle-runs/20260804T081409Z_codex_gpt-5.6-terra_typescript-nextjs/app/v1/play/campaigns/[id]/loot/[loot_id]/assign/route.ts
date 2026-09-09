import { NextResponse } from "next/server";
import { assignPlayCampaignLoot } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; loot_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, loot_id } = await params;
  const result = assignPlayCampaignLoot(id, loot_id, actor);
  if (result.result === "assigned") return NextResponse.json(result.loot);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Loot cannot be assigned" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or loot not found" }, { status: 404 });
}
