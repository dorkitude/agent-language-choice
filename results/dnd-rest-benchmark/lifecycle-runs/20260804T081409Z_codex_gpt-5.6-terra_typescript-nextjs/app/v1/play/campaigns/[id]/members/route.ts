import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { addPlayCampaignMember } from "../../../../../lib/play-campaigns";
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
  if (role !== "player") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.character_id) || !isNonEmptyString(body.name) || !isNonEmptyString(body.class)) {
    return badRequest();
  }

  const { id } = await params;
  const member = { username: actor, character_id: body.character_id, name: body.name, class: body.class };
  const result = addPlayCampaignMember(id, member);
  if (result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result === "conflict") return NextResponse.json({ error: "Unable to join campaign" }, { status: 409 });
  return NextResponse.json(member, { status: 201 });
}
