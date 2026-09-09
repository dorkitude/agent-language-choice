import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../../../lib/http";
import { recordPlayCampaignDeathSave } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || (body.outcome !== "success" && body.outcome !== "failure")) return badRequest();

  const { id, char_id } = await params;
  const result = recordPlayCampaignDeathSave(id, char_id, actor, body.outcome);
  if (result.result === "recorded") return NextResponse.json(result.deathSaves, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Character cannot make a death save" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
