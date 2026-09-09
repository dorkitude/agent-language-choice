import { NextResponse } from "next/server";
import { readPlayCampaignSpectatorView } from "../../../../../lib/play-campaigns";

export const runtime = "nodejs";

function spectatorIdFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer spectator-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const spectatorId = authorization.slice(prefix.length);
  return spectatorId.length > 0 ? spectatorId : undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const authorization = request.headers.get("authorization");
  const spectatorId = spectatorIdFromAuthorization(request);
  if (!spectatorId) {
    const isSessionToken = authorization?.startsWith("Bearer session-") && authorization.length > "Bearer session-".length;
    return NextResponse.json({ error: isSessionToken ? "Forbidden" : "Unauthorized" }, { status: isSessionToken ? 403 : 401 });
  }

  const result = readPlayCampaignSpectatorView((await params).id, spectatorId);
  if (result.result === "found") return NextResponse.json(result.view);
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Unauthorized" }, {
    status: result.result === "forbidden" ? 403 : 401,
  });
}
