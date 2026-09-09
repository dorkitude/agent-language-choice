import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import {
  preparePlayCampaignCharacterSpells,
  readPlayCampaignCharacterPreparedSpells,
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

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !Array.isArray(body.spell_ids) || !body.spell_ids.every(isNonEmptyString)) return badRequest();

  const { id, char_id } = await params;
  const result = preparePlayCampaignCharacterSpells(id, char_id, actor, body.spell_ids);
  if (result.result === "updated") return NextResponse.json(result.preparedSpells);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest("Prepared spells are not valid for this character");
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; char_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, char_id } = await params;
  const result = readPlayCampaignCharacterPreparedSpells(id, char_id, actor);
  if (result.result === "found") return NextResponse.json(result.preparedSpells);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or character not found" }, { status: 404 });
}
