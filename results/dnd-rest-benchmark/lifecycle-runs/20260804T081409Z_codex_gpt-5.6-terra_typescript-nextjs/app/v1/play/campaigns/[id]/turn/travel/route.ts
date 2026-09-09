import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../lib/http";
import { appendPlayCampaignTravel } from "../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../lib/users";

export const runtime = "nodejs";

function actorFromAuthorization(request: Request): string | undefined {
  const authorization = request.headers.get("authorization");
  const prefix = "Bearer session-";
  if (!authorization?.startsWith(prefix)) return undefined;
  const username = authorization.slice(prefix.length);
  return username.length > 0 ? username : undefined;
}

function roleForActor(actor: string): "dm" | "player" | undefined {
  if (actor === "dm") return "dm";
  if (actor === "player" || actor === "player-a" || actor === "player-b") return "player";
  return userRole(actor);
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await jsonBody(request);
  if (!isRecord(body) || !isNonEmptyString(body.destination_id)) return badRequest();

  const { id } = await params;
  const result = appendPlayCampaignTravel(id, actor, body.destination_id);
  switch (result.result) {
    case "not_found":
      return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
    case "forbidden":
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    case "conflict":
      return NextResponse.json({ error: "Not your turn or invalid destination" }, { status: 409 });
    case "created":
      return NextResponse.json(result.travel, { status: 201 });
  }
}
