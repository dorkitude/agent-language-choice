import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignAuditEvent, readPlayCampaignAuditEvents } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

function known(username: string): boolean {
  return username === "dm" || username === "player" || username === "player-a" || username === "player-b" || Boolean(userRole(username));
}

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return unauthorized();
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.kind) || !isNonEmptyString(body.correlation_id)) return badRequest();
  const result = createPlayCampaignAuditEvent((await params).id, who, {
    kind: body.kind,
    correlation_id: body.correlation_id,
  });
  if (result.result === "created") return NextResponse.json(result.entry, { status: 201 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Correlation ID already exists" }, { status: 409 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who || !known(who)) return unauthorized();
  const result = readPlayCampaignAuditEvents((await params).id, who);
  if (result.result === "found") return NextResponse.json({ entries: result.entries });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
