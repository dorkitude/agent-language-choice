import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../../lib/http";
import { readyPlayCampaignEncounterAction } from "../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function isKnownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; enc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !isKnownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.trigger)) return badRequest();

  const { id, enc_id } = await params;
  const result = readyPlayCampaignEncounterAction(id, enc_id, actor, body.trigger);
  if (result.result === "created") return NextResponse.json(result.ready, { status: 201 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Out of turn or encounter has no combatants" }, { status: 409 });
}
