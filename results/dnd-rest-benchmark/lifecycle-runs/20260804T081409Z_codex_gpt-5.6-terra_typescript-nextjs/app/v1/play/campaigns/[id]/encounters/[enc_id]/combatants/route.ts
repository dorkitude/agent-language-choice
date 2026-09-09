import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { addPlayCampaignEncounterCombatant } from "../../../../../../../lib/play-campaigns";
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
  if (!isRecord(body) || !isNonEmptyString(body.member) || !isInteger(body.initiative)) return badRequest();

  const { id, enc_id } = await params;
  const result = addPlayCampaignEncounterCombatant(id, enc_id, actor, body.member, body.initiative);
  if (result.result === "created") return NextResponse.json(result.combatant, { status: 201 });
  if (result.result === "invalid") return NextResponse.json({ error: "Member not found" }, { status: 400 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Member already bound" }, { status: 409 });
}
