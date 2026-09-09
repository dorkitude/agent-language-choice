import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { readPlayCampaignSafeTurns, submitPlayCampaignSafeTurn } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.submission_id) || !isNonEmptyString(body.action)
    || !isInteger(body.expected_turn) || body.expected_turn <= 0) return badRequest();
  const result = submitPlayCampaignSafeTurn((await params).id, actor, {
    submission_id: body.submission_id,
    action: body.action,
    expected_turn: body.expected_turn,
  });
  if (result.result === "created") return NextResponse.json(result.turn, { status: 201 });
  if (result.result === "stale") return NextResponse.json({ current_turn: result.current_turn }, { status: 409 });
  if (result.result === "duplicate") return NextResponse.json({ error: "Duplicate submission" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignSafeTurns((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ current_turn: result.current_turn, accepted: result.accepted });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
