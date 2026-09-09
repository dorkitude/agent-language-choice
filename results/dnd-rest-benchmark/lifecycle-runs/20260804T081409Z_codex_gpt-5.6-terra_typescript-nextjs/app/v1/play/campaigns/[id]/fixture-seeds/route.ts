import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { seedPlayCampaignFixture } from "../../../../../lib/play-campaigns";

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
  if (!isRecord(body) || body.fixture_id !== "canonical-v1") return badRequest();
  const result = seedPlayCampaignFixture((await params).id, actor);
  if (result.result === "seeded") return NextResponse.json(result.fixture, { status: 201 });
  if (result.result === "existing") return NextResponse.json(result.fixture);
  return NextResponse.json(
    { error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" },
    { status: result.result === "forbidden" ? 403 : 404 },
  );
}
