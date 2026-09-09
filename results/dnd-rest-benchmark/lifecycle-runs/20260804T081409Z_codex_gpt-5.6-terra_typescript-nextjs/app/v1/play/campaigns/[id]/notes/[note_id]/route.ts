import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";
import { readPlayCampaignNote, updatePlayCampaignNote } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";
export const runtime = "nodejs";
function actor(request: Request) { const value = request.headers.get("authorization"), prefix = "Bearer session-"; return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined; }
function known(value: string) { return value === "dm" || value === "player" || value === "player-a" || value === "player-b" || Boolean(userRole(value)); }
function reply(result: "not_found" | "forbidden") { return NextResponse.json({ error: result === "forbidden" ? "Forbidden" : "Campaign or note not found" }, { status: result === "forbidden" ? 403 : 404 }); }
export async function GET(request: Request, { params }: { params: Promise<{ id: string; note_id: string }> }) { const who = actor(request); if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); const p = await params; const result = readPlayCampaignNote(p.id, p.note_id, who); return result.result === "found" ? NextResponse.json(result.note) : reply(result.result); }
export async function PUT(request: Request, { params }: { params: Promise<{ id: string; note_id: string }> }) { const who = actor(request); if (!who || !known(who)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 }); const body = await jsonBody(request); if (!isRecord(body) || !isNonEmptyString(body.text) || (body.visibility !== "private" && body.visibility !== "party")) return badRequest(); const p = await params; const result = updatePlayCampaignNote(p.id, p.note_id, who, { text: body.text, visibility: body.visibility }); return result.result === "updated" ? NextResponse.json(result.note) : reply(result.result); }
