import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignIdempotentEvent, readPlayCampaignIdempotentEvents } from "../../../../../lib/play-campaigns";

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

  const idempotencyKey = request.headers.get("idempotency-key");
  if (!idempotencyKey || idempotencyKey.trim().length === 0) return badRequest();
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.event_id) || !isNonEmptyString(body.value)) return badRequest();

  const result = createPlayCampaignIdempotentEvent((await params).id, actor, {
    event_id: body.event_id,
    value: body.value,
    idempotency_key: idempotencyKey,
  });
  if (result.result === "created") return NextResponse.json(result.event, { status: 201 });
  if (result.result === "replayed") return NextResponse.json(result.event);
  if (result.result === "conflict") return NextResponse.json({ error: "Idempotency conflict" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const result = readPlayCampaignIdempotentEvents((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ events: result.events });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
