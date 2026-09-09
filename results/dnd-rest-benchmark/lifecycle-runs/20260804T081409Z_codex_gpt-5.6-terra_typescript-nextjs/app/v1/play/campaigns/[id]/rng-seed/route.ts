import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { configurePlayCampaignRngSeed } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!value?.startsWith(prefix) || value.length === prefix.length) return undefined;
  return value.slice(prefix.length);
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.seed)) return badRequest();
  const result = configurePlayCampaignRngSeed((await params).id, who, body.seed);
  if (result.result === "configured") return NextResponse.json(result.ledger);
  if (result.result === "conflict") return NextResponse.json({ error: "RNG seed already configured" }, { status: 409 });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, { status: result.result === "forbidden" ? 403 : 404 });
}
