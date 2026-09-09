import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { importPlayCampaign, type PlayCampaignImport } from "../../../../../lib/play-campaigns";
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

function validSnapshot(body: unknown): body is PlayCampaignImport {
  if (!isRecord(body)) return false;
  const keys = Object.keys(body);
  return keys.length === 3 && keys.includes("version") && keys.includes("story") && keys.includes("status")
    && body.version === 1 && typeof body.story === "string" && body.story.length > 0
    && (body.status === "lobby" || body.status === "started");
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (!validSnapshot(body)) return badRequest();

  const result = importPlayCampaign((await params).id, actor, body);
  if (result.result === "imported") {
    return NextResponse.json({ version: result.snapshot.version, story: result.snapshot.story, status: result.snapshot.status });
  }
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  return NextResponse.json({ error: "Forbidden" }, { status: 403 });
}
