import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignSearchRecord, readPlayCampaignSearchRecords } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function knownActor(actor: string): boolean {
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || Boolean(userRole(actor));
}

function parseNonnegativeInteger(value: string | null, fallback: number): number | undefined {
  if (value === null) return fallback;
  if (!/^\d+$/.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.record_id) || !isNonEmptyString(body.text)) return badRequest();

  const result = createPlayCampaignSearchRecord((await params).id, actor, { record_id: body.record_id, text: body.text });
  if (result.result === "created") return NextResponse.json(result.record, { status: 201 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return badRequest();
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { searchParams } = new URL(request.url);
  const limit = parseNonnegativeInteger(searchParams.get("limit"), 2);
  const cursor = parseNonnegativeInteger(searchParams.get("cursor"), 0);
  if (limit === undefined || limit < 1 || limit > 3 || cursor === undefined) return badRequest();

  const result = readPlayCampaignSearchRecords((await params).id, actor, searchParams.get("q") ?? undefined, limit, cursor);
  if (result.result === "found") return NextResponse.json({ records: result.records, next_cursor: result.next_cursor });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
