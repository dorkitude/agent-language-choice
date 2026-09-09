import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../lib/http";
import { damagePlayCampaignCharacter } from "../../../../../../../lib/play-campaigns";
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
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isInteger(body.amount) || body.amount <= 0) return badRequest();

  const { id, char_id } = await params;
  const result = damagePlayCampaignCharacter(id, char_id, actor, body.amount);
  if (result.result === "damaged") return NextResponse.json(result.health);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
