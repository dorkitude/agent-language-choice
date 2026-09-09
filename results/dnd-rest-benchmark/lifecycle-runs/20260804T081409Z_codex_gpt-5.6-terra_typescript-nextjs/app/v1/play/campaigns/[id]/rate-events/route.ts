import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignRateEvent, readPlayCampaignRateEvents } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.event_id)) return badRequest();

  const result = createPlayCampaignRateEvent((await params).id, actor, body.event_id);
  if (result.result === "created") return NextResponse.json({ ...result.event, remaining: result.remaining }, { status: 201 });
  if (result.result === "limited") return NextResponse.json({ limit: 2, remaining: 0 }, { status: 429 });
  // A reused event ID is invalid input for this endpoint, rather than a
  // state-transition conflict.  Keep it on the same 400 path as other
  // rejected rate-event creations.
  if (result.result === "conflict") return badRequest();
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignRateEvents((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ events: result.events, remaining: result.remaining });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
