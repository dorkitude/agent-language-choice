import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { playCampaignExists } from "../../../../../lib/play-campaigns";
import { setMaintenanceMode } from "../../../../../lib/service-mode";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || Object.keys(body).length !== 1 || typeof body.maintenance !== "boolean") return badRequest();

  const { id } = await params;
  if (!playCampaignExists(id)) return NextResponse.json({ error: "Campaign not found" }, { status: 404 });

  return NextResponse.json({ maintenance: setMaintenanceMode(body.maintenance) });
}
