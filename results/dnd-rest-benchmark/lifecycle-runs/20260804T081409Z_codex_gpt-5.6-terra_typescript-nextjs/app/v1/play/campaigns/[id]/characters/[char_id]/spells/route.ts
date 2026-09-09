import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { addPlayCampaignCharacterSpell, readPlayCampaignCharacterSpells } from "../../../../../../../lib/play-campaigns";
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
  if (
    !isRecord(body) ||
    !isNonEmptyString(body.spell_id) ||
    !isNonEmptyString(body.name) ||
    !isInteger(body.level) || body.level < 0 || body.level > 9
  ) return badRequest();

  const { id, char_id } = await params;
  const result = addPlayCampaignCharacterSpell(id, char_id, actor, {
    spell_id: body.spell_id,
    name: body.name,
    level: body.level,
  });
  if (result.result === "created") return NextResponse.json(result.spell, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Spell already known" }, { status: 409 });
  if (result.result === "invalid") return badRequest("Spell is not valid for this character class");
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, char_id } = await params;
  const result = readPlayCampaignCharacterSpells(id, char_id, actor);
  if (result.result === "found") return NextResponse.json({ spells: result.spells });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
