import { NextResponse } from "next/server";
import { endPlayCampaignEncounter } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; enc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const { id, enc_id } = await params;
  const result = endPlayCampaignEncounter(id, enc_id, actor);
  if (result.result === "ended") return NextResponse.json(result.campaign);
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign is not in combat" }, { status: 409 });
}
