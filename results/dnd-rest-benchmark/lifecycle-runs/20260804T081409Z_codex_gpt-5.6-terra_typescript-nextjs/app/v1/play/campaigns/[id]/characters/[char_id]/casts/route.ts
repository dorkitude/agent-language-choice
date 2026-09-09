import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import {
  castPlayCampaignCharacterSpell,
  readPlayCampaignCharacterCasts,
} from "../../../../../../../lib/play-campaigns";
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
  if (!isRecord(body) || !isNonEmptyString(body.spell_id) || !isNonEmptyString(body.target)) return badRequest();

  const { id, char_id } = await params;
  const result = castPlayCampaignCharacterSpell(id, char_id, actor, body.spell_id, body.target);
  if (result.result === "created") return NextResponse.json(result.cast, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest("Spell is not currently prepared or character cannot cast spells");
  if (result.result === "exhausted") return NextResponse.json({ error: "No spell slots remaining" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id } = await params;
  const result = readPlayCampaignCharacterCasts(id, char_id, actor);
  if (result.result === "found") return NextResponse.json({ casts: result.casts });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
