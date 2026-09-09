import { NextResponse } from "next/server";
import { isCharacterLevel } from "../../../../../../../lib/characters";
import { badRequest, isRecord, jsonBody } from "../../../../../../../lib/http";
import { levelUpPlayCampaignCharacter } from "../../../../../../../lib/play-campaigns";
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
  if (!isRecord(body) || !isCharacterLevel(body.level)) return badRequest();

  const { id, char_id } = await params;
  const result = levelUpPlayCampaignCharacter(id, char_id, actor, body.level);
  if (result.result === "leveled") return NextResponse.json(result.character);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return badRequest(result.result === "invalid" ? "Level must be exactly one higher than the current level" : "Campaign or character not found");
}
