import { NextResponse } from "next/server";
import { readPlayCampaignMetrics } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function actor(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  return value?.startsWith(prefix) && value.length > prefix.length ? value.slice(prefix.length) : undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = actor(request);
  if (!who) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignMetrics((await params).id, who);
  if (result.result === "found") return NextResponse.json(result.metrics);
  return NextResponse.json(
    { error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" },
    { status: result.result === "forbidden" ? 403 : 404 },
  );
}
