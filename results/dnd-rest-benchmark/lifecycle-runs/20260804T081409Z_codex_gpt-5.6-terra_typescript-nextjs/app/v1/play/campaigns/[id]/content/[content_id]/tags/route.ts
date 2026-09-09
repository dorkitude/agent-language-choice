import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../../../lib/http";
import { replacePlayCampaignContentTags } from "../../../../../../../lib/play-campaigns";
import { userRole } from "../../../../../../../lib/users";

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

function tagsFromBody(value: unknown): string[] | undefined {
  if (!isRecord(value) || !Array.isArray(value.tags) || !value.tags.every(isNonEmptyString) ||
    new Set(value.tags).size !== value.tags.length) return undefined;
  return value.tags;
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string; content_id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const tags = tagsFromBody(await jsonBody(request));
  if (!tags) return badRequest();

  const { id, content_id } = await params;
  const result = replacePlayCampaignContentTags(id, content_id, actor, tags);
  if (result.result === "updated") return NextResponse.json(result.content);
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign or content not found" }, { status: 404 });
}
