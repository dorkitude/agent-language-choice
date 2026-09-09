import { NextResponse } from "next/server";
import { badRequest } from "../../../../../lib/http";
import { readPlayCampaignFeedEvents } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function nonnegativeInteger(value: string | null, fallback: number): number | undefined {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const search = new URL(request.url).searchParams;
  const cursor = nonnegativeInteger(search.get("cursor"), 0);
  const limit = nonnegativeInteger(search.get("limit"), 2);
  if (cursor === undefined || limit === undefined || limit < 1 || limit > 3) return badRequest();

  const result = readPlayCampaignFeedEvents((await params).id, actor, cursor, limit);
  if (result.result === "found") return NextResponse.json({ events: result.events, next_cursor: cursor + result.events.length });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
