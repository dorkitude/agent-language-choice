import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../../lib/http";
import { transferPlayCampaignCharacterCurrency } from "../../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../../lib/users";

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
  if (!isRecord(body) || !isNonEmptyString(body.to_character_id) || !isInteger(body.gold) || body.gold <= 0) {
    return badRequest();
  }

  const { id, char_id } = await params;
  const result = transferPlayCampaignCharacterCurrency(id, char_id, actor, body.to_character_id, body.gold);
  if (result.result === "transferred") return NextResponse.json(result.transfer, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest();
  if (result.result === "insufficient") return NextResponse.json({ error: "Insufficient gold" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
