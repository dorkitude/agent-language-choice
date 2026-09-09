import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { addPlayCampaignEncounterCondition } from "../../../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; enc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.target) || !isNonEmptyString(body.condition) || !isInteger(body.duration_rounds) || body.duration_rounds <= 0) return badRequest();

  const { id, enc_id } = await params;
  const result = addPlayCampaignEncounterCondition(id, enc_id, actor, body.target, body.condition, body.duration_rounds);
  if (result.result === "created") return NextResponse.json({ target: body.target, conditions: result.conditions }, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return NextResponse.json({ error: "Target not found" }, { status: 400 });
  return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
}
