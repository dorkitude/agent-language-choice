import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { createPlayCampaignNpcDialogue, readPlayCampaignNpcDialogue } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

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

export async function POST(request: Request, { params }: { params: Promise<{ id: string; npc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.dialogue_id) || !isNonEmptyString(body.speaker) ||
    !isNonEmptyString(body.text) || (body.visibility !== "public" && body.visibility !== "private")) return badRequest();

  const { id, npc_id } = await params;
  const result = createPlayCampaignNpcDialogue(id, npc_id, actor, {
    dialogue_id: body.dialogue_id,
    speaker: body.speaker,
    text: body.text,
    visibility: body.visibility,
  });
  if (result.result === "created") return NextResponse.json(result.dialogue, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Dialogue already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign or NPC not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string; npc_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, npc_id } = await params;
  const result = readPlayCampaignNpcDialogue(id, npc_id, actor);
  if (result.result === "found") return NextResponse.json({ npc_id, entries: result.entries });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or NPC not found" }, { status: 404 });
}
