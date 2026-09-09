import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";
import { createPlayCampaignModerationReport, readPlayCampaignModerationReports } from "../../../../../../lib/play-campaigns";

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
  if (!isRecord(body) || !isNonEmptyString(body.report_id) || !isNonEmptyString(body.target_id) || !isNonEmptyString(body.reason)) return badRequest();
  const result = createPlayCampaignModerationReport((await params).id, actor, {
    report_id: body.report_id,
    target_id: body.target_id,
    reason: body.reason,
  });
  if (result.result === "created") return NextResponse.json(result.report, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Report already exists" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignModerationReports((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ reports: result.reports });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
