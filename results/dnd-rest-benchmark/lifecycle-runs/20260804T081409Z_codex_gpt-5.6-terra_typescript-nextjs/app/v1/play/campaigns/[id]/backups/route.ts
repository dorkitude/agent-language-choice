import { NextResponse } from "next/server";
import { createPlayCampaignBackup, readPlayCampaignBackups } from "../../../../../lib/play-campaigns";
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

function responseFor(result: { result: "not_found" | "forbidden" }) {
  return result.result === "not_found"
    ? NextResponse.json({ error: "Campaign not found" }, { status: 404 })
    : NextResponse.json({ error: "Forbidden" }, { status: 403 });
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = createPlayCampaignBackup((await params).id, actor);
  if (result.result === "created") return NextResponse.json(result.backup, { status: 201 });
  return responseFor(result);
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const result = readPlayCampaignBackups((await params).id, actor);
  if (result.result === "found") return NextResponse.json({ backups: result.backups });
  return responseFor(result);
}
