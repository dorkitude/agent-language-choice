import { NextResponse } from "next/server";
import { badRequest, isInteger, isRecord, jsonBody } from "../../../../../../../../lib/http";
import { delayPlayCampaignEncounterTurn } from "../../../../../../../../lib/play-campaigns";
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
  const targetIndex = isRecord(body) && [
    body.index,
    body.target_index,
    body.position,
    body.new_index,
    body.new_position,
    body.to_index,
    body.to,
    body.delay_to,
  ].find(isInteger);
  if (!isInteger(targetIndex)) return badRequest();

  const { id, enc_id } = await params;
  const result = delayPlayCampaignEncounterTurn(id, enc_id, actor, targetIndex);
  if (result.result === "delayed") return NextResponse.json({ order: result.order });
  if (result.result === "invalid") return badRequest();
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Out of turn or encounter has no combatants" }, { status: 409 });
}
