import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import {
  clearPlayCampaignCharacterConcentration,
  readPlayCampaignCharacterConcentration,
  setPlayCampaignCharacterConcentration,
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

function responseFor(result: { result: string; concentration?: unknown }) {
  if (result.result === "updated" || result.result === "found" || result.result === "cleared") return NextResponse.json(result.concentration);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.spell_id) || !isNonEmptyString(body.target) || !isInteger(body.duration_turns) || body.duration_turns < 1) return badRequest();
  const { id, char_id } = await params;
  const result = setPlayCampaignCharacterConcentration(id, char_id, actor, body.spell_id, body.target, body.duration_turns);
  if (result.result === "invalid") return badRequest("Spell is not currently prepared or character cannot cast spells");
  return responseFor(result);
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id } = await params;
  return responseFor(readPlayCampaignCharacterConcentration(id, char_id, actor));
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id, char_id } = await params;
  return responseFor(clearPlayCampaignCharacterConcentration(id, char_id, actor));
}
