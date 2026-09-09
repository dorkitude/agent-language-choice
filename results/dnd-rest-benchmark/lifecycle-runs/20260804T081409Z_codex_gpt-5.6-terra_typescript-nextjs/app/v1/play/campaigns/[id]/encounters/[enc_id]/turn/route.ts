import { NextResponse } from "next/server";
import { readPlayCampaignEncounterTurn } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

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

export async function GET(request: Request, { params }: { params: Promise<{ id: string; enc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !isKnownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, enc_id } = await params;
  const result = readPlayCampaignEncounterTurn(id, enc_id, actor);
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign or encounter not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Encounter has no combatants" }, { status: 409 });
  if (result.result === "found") return NextResponse.json(result.turn);
  return NextResponse.json({ error: "Unable to read encounter turn" }, { status: 500 });
}
