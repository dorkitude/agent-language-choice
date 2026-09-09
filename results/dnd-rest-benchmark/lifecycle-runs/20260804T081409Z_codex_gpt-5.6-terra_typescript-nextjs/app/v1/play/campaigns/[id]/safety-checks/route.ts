import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { submitPlayCampaignSafetyCheck } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

function validNonBlankString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function validTags(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every(validNonBlankString) && new Set(value).size === value.length;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !validNonBlankString(body.event_id) || !validNonBlankString(body.text)
    || (body.kind !== "narration" && body.kind !== "chat") || !validTags(body.tags)) return badRequest();
  const result = submitPlayCampaignSafetyCheck((await params).id, actor, {
    event_id: body.event_id, kind: body.kind, text: body.text, tags: body.tags,
  });
  if (result.result === "created") return NextResponse.json(result.event, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Safety check rejected" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
