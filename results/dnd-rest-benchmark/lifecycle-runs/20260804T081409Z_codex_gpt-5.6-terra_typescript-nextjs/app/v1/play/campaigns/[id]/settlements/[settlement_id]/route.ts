import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";
import { replacePlayCampaignSettlement, type PlayCampaignSettlement } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

export const runtime = "nodejs";

const availabilities = new Set<PlayCampaignSettlement["availability"]>(["open", "limited", "closed"]);

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

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; settlement_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.name) || !Array.isArray(body.services) || body.services.length === 0 ||
    typeof body.availability !== "string" || !availabilities.has(body.availability as PlayCampaignSettlement["availability"])) return badRequest();
  const services = body.services.map((service) => typeof service === "string" ? service.trim() : "");
  if (services.some((service) => service.length === 0) || new Set(services).size !== services.length) return badRequest();
  const { id, settlement_id } = await params;
  const result = replacePlayCampaignSettlement(id, settlement_id, actor, {
    name: body.name,
    services,
    availability: body.availability as PlayCampaignSettlement["availability"],
  });
  if (result.result === "updated") return NextResponse.json(result.settlement);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Settlement not found" }, { status: 404 });
}
