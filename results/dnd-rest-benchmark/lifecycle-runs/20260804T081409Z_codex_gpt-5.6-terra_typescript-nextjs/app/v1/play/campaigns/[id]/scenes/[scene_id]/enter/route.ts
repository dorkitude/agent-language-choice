import { NextResponse } from "next/server";
import { enterPlayCampaignScene } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; scene_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || roleForActor(actor) === undefined) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const { id, scene_id } = await params;
  const result = enterPlayCampaignScene(id, actor, scene_id);
  if (result.result === "entered") return NextResponse.json({ current_scene_id: result.scene.id, name: result.scene.name });
  if (result.result === "not_found") return NextResponse.json({ error: "Scene not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Scene is closed" }, { status: 409 });
}
