import { NextResponse } from "next/server";
import { badRequest, isInteger, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { appendPlayCampaignRngRoll } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!value?.startsWith(prefix) || value.length === prefix.length) return undefined;
  return value.slice(prefix.length);
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.roll_id) || !isInteger(body.sides) || body.sides < 2 || body.sides > 100) return badRequest();
  const result = appendPlayCampaignRngRoll((await params).id, who, { roll_id: body.roll_id, sides: body.sides });
  if (result.result === "created") return NextResponse.json(result.roll, { status: 201 });
  if (result.result === "conflict") return NextResponse.json({ error: "Roll already exists" }, { status: 409 });
  if (result.result === "unconfigured") return NextResponse.json({ error: "RNG seed not configured" }, { status: 409 });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
