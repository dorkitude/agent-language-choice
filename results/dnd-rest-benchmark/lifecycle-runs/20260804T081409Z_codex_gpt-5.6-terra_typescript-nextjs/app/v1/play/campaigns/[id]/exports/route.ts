import { NextResponse } from "next/server";
import { createPlayCampaignExport, readPlayCampaignExports } from "../../../../../lib/play-campaigns";
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

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

function responseFor(result: { result: "not_found" | "forbidden" }) {
  return result.result === "not_found"
    ? NextResponse.json({ error: "Campaign not found" }, { status: 404 })
    : NextResponse.json({ error: "Forbidden" }, { status: 403 });
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return unauthorized();
  const result = createPlayCampaignExport((await params).id, actor);
  if (result.result === "created") return NextResponse.json(result.export, { status: 201 });
  return responseFor(result);
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return unauthorized();
  const result = readPlayCampaignExports((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ exports: result.exports });
  return responseFor(result);
}
