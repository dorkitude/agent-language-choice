import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignClue, readPlayCampaignClues, type PlayCampaignClue } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

function hasOwn(object: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.clue_id) || !isNonEmptyString(body.text) ||
    (body.audience !== "character" && body.audience !== "party" && body.audience !== "hidden")) return badRequest();
  const isCharacterClue = body.audience === "character";
  if ((isCharacterClue && !isNonEmptyString(body.character_id)) || (!isCharacterClue && hasOwn(body, "character_id"))) {
    return badRequest();
  }

  const clue: PlayCampaignClue = isCharacterClue
    ? { clue_id: body.clue_id, text: body.text, audience: body.audience, character_id: body.character_id as string }
    : { clue_id: body.clue_id, text: body.text, audience: body.audience };
  const { id } = await params;
  const result = createPlayCampaignClue(id, actor, clue);
  if (result.result === "created") return NextResponse.json(result.clue, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "invalid") return badRequest();
  if (result.result === "conflict") return NextResponse.json({ error: "Clue already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const result = readPlayCampaignClues(id, actor);
  if (result.result === "found") return NextResponse.json({ clues: result.clues });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
