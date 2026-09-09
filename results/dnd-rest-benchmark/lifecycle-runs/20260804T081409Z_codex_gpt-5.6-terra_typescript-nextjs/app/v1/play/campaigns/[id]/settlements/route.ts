import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignSettlement, readPlayCampaignSettlements, type PlayCampaignSettlement } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

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

function settlementFromBody(body: unknown): Omit<PlayCampaignSettlement, "discovered_by"> | undefined {
  if (!isRecord(body) || !isNonEmptyString(body.settlement_id) || !isNonEmptyString(body.name) ||
    !Array.isArray(body.services) || body.services.length === 0 || typeof body.availability !== "string" ||
    !availabilities.has(body.availability as PlayCampaignSettlement["availability"])) return undefined;
  const services = body.services.map((service) => typeof service === "string" ? service.trim() : "");
  if (services.some((service) => service.length === 0) || new Set(services).size !== services.length) return undefined;
  return { settlement_id: body.settlement_id, name: body.name, services, availability: body.availability as PlayCampaignSettlement["availability"] };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const settlement = settlementFromBody(await jsonBody(request));
  if (!settlement) return badRequest();
  const { id } = await params;
  const result = createPlayCampaignSettlement(id, actor, settlement);
  if (result.result === "created") return NextResponse.json(result.settlement, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Settlement already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const result = readPlayCampaignSettlements(id, actor);
  if (result.result === "found") return NextResponse.json({ settlements: result.settlements });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
