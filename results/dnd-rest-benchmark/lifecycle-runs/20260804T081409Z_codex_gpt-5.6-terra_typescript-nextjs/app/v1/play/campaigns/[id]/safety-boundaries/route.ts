import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { readPlayCampaignSafetyBoundaries, replacePlayCampaignSafetyBoundaries } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

function validTags(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every((tag) => typeof tag === "string" && tag.trim().length > 0)
    && new Set(value).size === value.length;
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !validTags(body.blocked_tags)) return badRequest();
  const result = replacePlayCampaignSafetyBoundaries((await params).id, actor, body.blocked_tags);
  if (result.result === "updated") return NextResponse.json({ blocked_tags: result.blocked_tags });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignSafetyBoundaries((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ blocked_tags: result.blocked_tags });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
