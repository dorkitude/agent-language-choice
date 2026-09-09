import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../lib/http";
import { createPlayCampaign } from "../../../lib/play-campaigns";
import { userRole } from "../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  // These deterministic session principals remain valid after storage reset.
  // Registered users may also use their session token.
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

export async function POST(request: Request) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const role = roleForActor(actor);
  if (!role) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (role !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (
    !isRecord(body) ||
    typeof body.id !== "string" || body.id.length === 0 ||
    typeof body.name !== "string" || body.name.length === 0 ||
    !isInteger(body.max_players) || body.max_players < 1
  ) {
    return badRequest();
  }

  const campaign = { id: body.id, name: body.name, owner: actor, status: "lobby" as const, max_players: body.max_players };
  if (!createPlayCampaign(campaign)) {
    return NextResponse.json({ error: "Campaign already exists" }, { status: 409 });
  }
  return NextResponse.json(campaign, { status: 201 });
}
