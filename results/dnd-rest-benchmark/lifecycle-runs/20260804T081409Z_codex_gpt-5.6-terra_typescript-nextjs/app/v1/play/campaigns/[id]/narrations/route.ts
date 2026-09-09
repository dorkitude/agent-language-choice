import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { appendPlayCampaignNarration } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

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

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const role = roleForActor(actor);
  if (!role) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.text)) return badRequest();

  const { id } = await params;
  const result = appendPlayCampaignNarration(id, actor, body.text);
  if (result.result !== "created") {
    if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  return NextResponse.json(result.narration, { status: 201 });
}
