import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { appendPlayCampaignProjectionEvent, type PlayCampaignProjectionEventInput } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.event_id) || (body.kind !== "set-story" && body.kind !== "increment-danger")) return badRequest();
  if (body.kind === "set-story" ? !isNonEmptyString(body.value) : Object.hasOwn(body, "value")) return badRequest();

  const event: PlayCampaignProjectionEventInput = body.kind === "set-story"
    ? { event_id: body.event_id, kind: "set-story", value: body.value as string }
    : { event_id: body.event_id, kind: "increment-danger" };
  const result = appendPlayCampaignProjectionEvent((await params).id, who,
    event);
  if (result.result === "created") return NextResponse.json(result.event, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Event already exists" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
