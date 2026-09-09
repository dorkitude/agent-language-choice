import { NextResponse } from "next/server";
import { badRequest, isRecord, jsonBody } from "../../../../../lib/http";
import { readPlayCampaignDocument, updatePlayCampaignDocument } from "../../../../../lib/play-campaigns";
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

function authenticate(request: Request): { actor: string; role: "dm" | "player" } | NextResponse {
  const actor = actorFromAuthorization(request);
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const role = roleForActor(actor);
  if (!role) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return { actor, role };
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const authentication = authenticate(request);
  if (authentication instanceof NextResponse) return authentication;
  if (authentication.role !== "dm") return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const body = await jsonBody(request);
  if (!isRecord(body) || typeof body.story !== "string" || typeof body.dm_notes !== "string") return badRequest();

  const { id } = await params;
  const result = updatePlayCampaignDocument(id, authentication.actor, { story: body.story, dm_notes: body.dm_notes });
  if (result.result !== "updated") {
    if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  return NextResponse.json(result.document);
}

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const authentication = authenticate(request);
  if (authentication instanceof NextResponse) return authentication;

  const { id } = await params;
  const result = readPlayCampaignDocument(id, authentication.actor);
  if (result.result !== "found") {
    if (result.result === "not_found") return NextResponse.json({ error: "Campaign not found" }, { status: 404 });
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  if (result.is_owner) return NextResponse.json(result.document);
  return NextResponse.json({ story: result.document.story });
}
