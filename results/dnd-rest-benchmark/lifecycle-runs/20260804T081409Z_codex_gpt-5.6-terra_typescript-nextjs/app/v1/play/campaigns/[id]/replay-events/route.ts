import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { appendPlayCampaignReplayEvent } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!value?.startsWith(prefix) || value.length === prefix.length) return undefined;
  const username = value.slice(prefix.length);
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || userRole(username)
    ? username
    : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.event_id) || !isNonEmptyString(body.text) || body.kind !== "append") return badRequest();

  const result = appendPlayCampaignReplayEvent((await params).id, who, { event_id: body.event_id, text: body.text });
  if (result.result === "created") return NextResponse.json(result.event, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Event already exists" }, { status: 409 });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
