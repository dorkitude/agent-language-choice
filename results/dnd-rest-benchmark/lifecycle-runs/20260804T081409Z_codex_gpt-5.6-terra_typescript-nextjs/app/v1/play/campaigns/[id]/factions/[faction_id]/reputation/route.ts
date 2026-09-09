import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { changePlayCampaignFactionReputation, readPlayCampaignFactionReputation } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; faction_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.character_id) || !isInteger(body.delta) || body.delta === 0 ||
    body.delta < -25 || body.delta > 25 || !isNonEmptyString(body.reason)) return badRequest();

  const { id, faction_id } = await params;
  const result = changePlayCampaignFactionReputation(id, faction_id, actor, {
    character_id: body.character_id,
    delta: body.delta,
    reason: body.reason,
  });
  if (result.result === "created") return NextResponse.json(result.entry, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest();
  return NextResponse.json({ error: "Campaign or faction not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; faction_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, faction_id } = await params;
  const result = readPlayCampaignFactionReputation(id, faction_id, actor);
  if (result.result === "found") return NextResponse.json({ faction_id, entries: result.entries });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or faction not found" }, { status: 404 });
}
