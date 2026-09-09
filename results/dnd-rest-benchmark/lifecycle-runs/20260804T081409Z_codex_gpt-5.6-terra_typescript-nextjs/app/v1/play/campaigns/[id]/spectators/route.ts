import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignSpectator } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const actor = authorization.slice(prefix.length);
  return actor.length > 0 ? actor : undefined;
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
  if (role !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.spectator_id)) return badRequest();

  const result = createPlayCampaignSpectator((await params).id, actor, body.spectator_id);
  if (result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result === "conflict") return NextResponse.json({ error: "Spectator already exists" }, { status: 409 });
  return NextResponse.json({ spectator_id: body.spectator_id, token: `spectator-${body.spectator_id}` }, { status: 201 });
}
