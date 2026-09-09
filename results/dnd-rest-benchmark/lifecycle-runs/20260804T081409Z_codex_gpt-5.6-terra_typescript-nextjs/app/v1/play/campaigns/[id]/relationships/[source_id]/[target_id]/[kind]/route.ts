import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../../lib/http";
import { updatePlayCampaignRelationship } from "../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../lib/users";

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

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string; source_id: string; target_id: string; kind: string }> },
) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isInteger(body.score) || body.score < -100 || body.score > 100) return badRequest();

  const { id, source_id, target_id, kind } = await params;
  const result = updatePlayCampaignRelationship(id, actor, source_id, target_id, kind, body.score);
  if (result.result === "updated") return NextResponse.json(result.edge);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Relationship not found" }, { status: 404 });
}
