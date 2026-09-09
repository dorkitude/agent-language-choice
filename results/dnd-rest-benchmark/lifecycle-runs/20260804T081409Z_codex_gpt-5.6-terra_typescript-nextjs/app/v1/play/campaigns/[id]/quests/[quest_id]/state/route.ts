import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../../../lib/http";
import { updatePlayCampaignQuestState } from "../../../../../../../lib/play-campaigns";
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

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; quest_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || (body.state !== "active" && body.state !== "completed")) return badRequest();

  const { id, quest_id } = await params;
  const result = updatePlayCampaignQuestState(id, quest_id, actor, body.state);
  if (result.result === "updated") return NextResponse.json(result.quest);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Invalid quest state transition" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or quest not found" }, { status: 404 });
}
