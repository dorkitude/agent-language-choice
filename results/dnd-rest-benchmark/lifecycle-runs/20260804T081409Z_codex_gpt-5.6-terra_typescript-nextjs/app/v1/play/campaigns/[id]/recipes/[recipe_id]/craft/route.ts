import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { craftPlayCampaignRecipe } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; recipe_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "player") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.character_id)) return badRequest();
  const { id, recipe_id } = await params;
  const result = craftPlayCampaignRecipe(id, recipe_id, body.character_id, actor);
  if (result.result === "crafted") return NextResponse.json(result.craft, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient ingredients" }, { status: 409 });
  return NextResponse.json({ error: "Recipe or character not found" }, { status: 404 });
}
