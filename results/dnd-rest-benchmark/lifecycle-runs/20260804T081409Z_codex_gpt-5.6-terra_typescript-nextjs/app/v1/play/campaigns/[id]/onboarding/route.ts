import { NextResponse } from "next/server";
import { readPlayCampaignOnboarding } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function authenticatedActor(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const actor = authorization.slice(prefix.length);
  if (actor.length === 0) return undefined;

  // Retain the deterministic principals used by the established play API.
  if (actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b") return actor;
  return userRole(actor) ? actor : undefined;
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = authenticatedActor(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const result = readPlayCampaignOnboarding((await params).id, actor);
  if (result.result === "found") return NextResponse.json(result.onboarding);
  return NextResponse.json(
    { error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" },
    { status: result.result === "forbidden" ? 403 : 404 },
  );
}
