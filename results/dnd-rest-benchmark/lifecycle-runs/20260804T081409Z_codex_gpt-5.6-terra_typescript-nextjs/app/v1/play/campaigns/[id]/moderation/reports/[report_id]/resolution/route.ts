import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../../lib/http";
import { resolvePlayCampaignModerationReport } from "../../../../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; report_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || (body.action !== "allow" && body.action !== "remove") || !isNonEmptyString(body.note)) return badRequest();
  const { id, report_id } = await params;
  const result = resolvePlayCampaignModerationReport(id, actor, report_id, { action: body.action, note: body.note });
  if (result.result === "resolved") return NextResponse.json(result.report);
  if (result.result === "conflict") return NextResponse.json({ error: "Report already resolved" }, { status: 409 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Report not found" }, { status: 404 });
}
