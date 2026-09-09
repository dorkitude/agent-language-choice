import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { migratePlayCampaignSnapshot } from "../../../../../lib/play-campaigns";
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

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !knownActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (!isRecord(body) || body.schema_version !== 1 || !isNonEmptyString(body.story)) return badRequest();

  const result = migratePlayCampaignSnapshot((await params).id, actor, body.story);
  if (result.result === "migrated") return NextResponse.json(result.state, { status: result.idempotent ? 200 : 201 });
  if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
  return NextResponse.json({ error: "Forbidden" }, { status: 403 });
}
