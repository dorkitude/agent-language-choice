import { NextResponse } from "next/server";
import { badRequest, isNonEmptyString, isRecord, jsonBody } from "../../../../../lib/http";
import { createPlayCampaignContent, readPlayCampaignContent, type PlayCampaignContent } from "../../../../../lib/play-campaigns";
import { userRole } from "../../../../../lib/users";

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

function contentFromBody(value: unknown): PlayCampaignContent | undefined {
  if (!isRecord(value) || !isNonEmptyString(value.content_id) || !isNonEmptyString(value.kind) ||
    !isNonEmptyString(value.text) || !Array.isArray(value.tags) || value.tags.length === 0 ||
    !value.tags.every(isNonEmptyString) || new Set(value.tags).size !== value.tags.length) return undefined;
  return { content_id: value.content_id, kind: value.kind, text: value.text, tags: value.tags };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (roleForActor(actor) !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  const content = contentFromBody(await jsonBody(request));
  if (!content) return badRequest();

  const result = createPlayCampaignContent((await params).id, actor, content);
  if (result.result === "created") return NextResponse.json(result.content, { status: 201 });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  if (result.result === "conflict") return NextResponse.json({ error: "Content already exists" }, { status: 409 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const actor = actorFromAuthorization(request);
  if (!actor || !roleForActor(actor)) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const excludeTag = new URL(request.url).searchParams.get("exclude_tag");
  if (excludeTag !== null && excludeTag.length === 0) return badRequest();

  const result = readPlayCampaignContent((await params).id, actor, excludeTag ?? undefined);
  if (result.result === "found") return NextResponse.json({ content: result.content });
  if (result.result === "forbidden") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
}
