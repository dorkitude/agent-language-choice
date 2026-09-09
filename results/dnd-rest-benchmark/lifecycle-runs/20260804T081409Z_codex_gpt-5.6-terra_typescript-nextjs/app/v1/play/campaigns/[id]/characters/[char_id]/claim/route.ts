import { NextResponse } from "next/server";
import { claimPlayCampaignCharacter } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  const role = actor ? roleForActor(actor) : undefined;
  if (!actor || !role) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (role !== "player") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const { id, char_id } = await params;
  const result = claimPlayCampaignCharacter(id, char_id, actor);
  if (result.result === "claimed") return NextResponse.json(result.owner, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Character already owned" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
