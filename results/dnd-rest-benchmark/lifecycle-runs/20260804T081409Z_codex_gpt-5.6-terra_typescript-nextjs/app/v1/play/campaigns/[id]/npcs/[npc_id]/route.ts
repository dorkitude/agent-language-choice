import { NextResponse } from "next/server";
import { readPlayCampaignNpc } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; npc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, npc_id } = await params;
  const result = readPlayCampaignNpc(id, npc_id, actor);
  if (result.result !== "found") {
    if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    return NextResponse.json({ error: "Campaign or NPC not found" }, { status: 404 });
  }
  if (result.is_owner) return NextResponse.json(result.npc);
  return NextResponse.json({ npc_id: result.npc.npc_id, name: result.npc.name, public_status: result.npc.public_status });
}
