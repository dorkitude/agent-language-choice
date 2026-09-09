import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignNote, readPlayCampaignNotes } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";
function actor(request: Request) { const value = request.headers.get("authorization"); const prefix = "Bearer session-"; return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined; }
function known(value: string) { return value === "dm" || value === "player" || value === "player-a" || value === "player-b" || Boolean(userRole(value)); }
function unauthorized() { return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); }

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request); if (!who || !known(who)) return unauthorized();
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.note_id) || !isNonEmptyString(body.text) || (body.visibility !== "private" && body.visibility !== "party")) return badRequest();
  const result = createPlayCampaignNote((await params).id, who, { note_id: body.note_id, text: body.text, visibility: body.visibility });
  if (result.result === "created") return NextResponse.json(result.note, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Note already exists" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request); if (!who || !known(who)) return unauthorized();
  const result = readPlayCampaignNotes((await params).id, who);
  if (result.result === "found") return NextResponse.json({ notes: result.notes });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
