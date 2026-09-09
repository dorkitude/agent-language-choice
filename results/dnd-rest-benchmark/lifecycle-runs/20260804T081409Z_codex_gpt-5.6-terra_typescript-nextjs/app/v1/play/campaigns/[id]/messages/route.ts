import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignMessage } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const value = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!value?.startsWith(prefix)) return undefined;
  const actor = value.slice(prefix.length);
  if (actor.length === 0) return undefined;
  return actor === "dm" || actor === "player" || actor === "player-a" || actor === "player-b" || userRole(actor) ? actor : undefined;
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.text)) return badRequest();

  const result = createPlayCampaignMessage((await params).id, actor, body.text);
  if (result.result === "created") return NextResponse.json(result.message, { status: 201 });
  return NextResponse.json({ error: result.result === "forbidden" ? "Forbidden" : "Campaign not found" }, {
    status: result.result === "forbidden" ? 403 : 404,
  });
}
