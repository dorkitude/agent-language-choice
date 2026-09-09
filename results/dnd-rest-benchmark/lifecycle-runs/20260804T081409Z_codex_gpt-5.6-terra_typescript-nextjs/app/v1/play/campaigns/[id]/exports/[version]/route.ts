import { NextResponse } from "next/server";
import { readPlayCampaignExport } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

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

export async function GET(request: Request, { params }: { params: Promise<{ id: string; version: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id, version: versionText } = await params;
  if (!/^[1-9][0-9]*$/.test(versionText)) return NextResponse.json({ error: "Export not found" }, { status: 404 });
  const result = readPlayCampaignExport(id, Number(versionText), actor);
  if (result.result === "found") return NextResponse.json(result.export);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Export not found" }, { status: 404 });
}
